"""rasterlabel.recovery

What is drawn but not yet on disk, written down somewhere a crash cannot reach.

Every stroke lives in a QGIS edit buffer until a save commits it. That is the
right design: it is fast, it is undoable, and one commit writes all five tables
at once. It has one cost, and the cost is the whole reason this module exists. A
buffer is memory. QGIS closing unexpectedly, a driver fault in some unrelated
plugin, a laptop running out of battery, or any defect of ours that drops a
buffer, all cost exactly the same thing: the work since the last save.

So after every stroke the pending features are written, as text, beside the
campaign. The file is a plain JSON Lines file a person can open and read_snapshot, which
matters: a recovery file nobody can inspect is a recovery file nobody trusts.
Writing it is a truncate and a rename, never an edit in place, so the file on
disk is always either the previous snapshot or the current one.

It is a net, not a second copy of the data. The GeoPackage remains the truth.
When a save succeeds there is nothing pending and the net is emptied, which is
also what makes a leftover file meaningful: a snapshot that is still there at the
next open can only mean that the session it belonged to never saved.
"""
import io
import json
import os
import time
import uuid


from .constants import BUILD, NAME, VERSION
from .errors import log
from .naming import long_path

RECOVERY_FOLDER = "recovery"
SNAPSHOT_SUFFIX = ".jsonl"
# A snapshot that has been dealt with is renamed, never deleted: .restored
# once its work has been put back, .discarded when it was turned down with
# Discard. "Not now" renames nothing, so the same file is offered again at the
# next open. Taking either ending off the name arms a file again.
RESTORED_SUFFIX = ".restored"
DISCARDED_SUFFIX = ".discarded"
# Above this many pending features a snapshot stops being cheap, and the number
# comes from measuring rather than from guessing. With the autosave at its
# default of twenty, a snapshot of twenty ordinary polygons takes two
# milliseconds and writes sixteen kilobytes; nobody will ever feel it. With the
# autosave off and four hundred detailed polygons waiting, the same snapshot
# takes seventy milliseconds and writes eleven megabytes, after every single
# stroke. That is the point at which the net starts costing what it is insuring,
# so that is where it says so. It still writes: being slow is better than losing
# the afternoon, and the message says how to make it stop.
MANY_PENDING = 400


def _is_null(value):
    """Whether this is QGIS's way of saying the field is empty."""
    try:
        if hasattr(value, "isNull") and value.isNull():
            return True
    except Exception:
        pass
    # A QVariant that has never been given a value prints like this and is the
    # one case str() would turn into nonsense.
    return type(value).__name__ == "QVariant" and not bool(value)


def _recovery_session():
    """A name for this run of the panel. The process id makes it readable, the
    random tail makes two QGIS windows on one machine not collide."""
    return "%d-%s" % (os.getpid(), uuid.uuid4().hex[:6])


class Recovery(object):

    def __init__(self, folder, campaign_id=""):
        self.folder = os.path.join(folder, RECOVERY_FOLDER)
        self.campaign_id = campaign_id
        self.session = _recovery_session()
        self.last = None            # what was written last, to skip rewrites
        self.complained = False     # say "cannot write the net" once, not 200 times
        self.warned = False         # and the same for "this is getting big"

    # ------------------------------------------------------------- paths
    @property
    def path(self):
        return os.path.join(self.folder, self.session + SNAPSHOT_SUFFIX)

    # ------------------------------------------------------- the snapshot
    def note(self, pending):
        """Write down everything in these buffers. pending is (role, layer).

        Returns the number of features written, or None when nothing was done.
        Never raises: a net that can bring the program down is worse than no net.
        """
        try:
            rows = []
            for role, lyr in pending:
                rows.extend(self._rows_of(role, lyr))
            if not rows:
                return self.clear()
            if len(rows) > MANY_PENDING and not self.warned:
                # Once. A line after every stroke would be its own problem.
                self.warned = True
                log("%d things are waiting to be saved, and the recovery file "
                    "is rewritten after every stroke, so drawing is going to "
                    "feel slow. Press Save, or turn the autosave back on under "
                    "Settings: both make this go away." % len(rows), loud=True)
            elif len(rows) <= MANY_PENDING:
                self.warned = False
            payload = [{"program": NAME, "version": VERSION, "build": BUILD,
                        "campaign": self.campaign_id,
                        "session": self.session,
                        "written": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "features": len(rows)}] + rows
            text = "\n".join(json.dumps(r, ensure_ascii=False)
                             for r in payload) + "\n"
            if text == self.last:
                return len(rows)
            self._write(text)
            self.last = text
            return len(rows)
        except Exception as err:
            if not self.complained:
                self.complained = True
                log("the recovery file cannot be written, so a crash would cost "
                    "the work since the last Save: %s" % err, loud=True)
            return None

    def _rows_of(self, role, lyr):
        out = []
        buf = None
        try:
            buf = lyr.editBuffer()
        except Exception:
            buf = None
        if buf is None:
            return out
        names = [f.name() for f in lyr.fields()]
        try:
            added = buf.addedFeatures()
        except Exception:
            added = {}
        for fid, f in (added or {}).items():
            row = {"role": role, "what": "added",
                   "wkt": self._wkt(f), "fields": self._fields(f, names)}
            if row["wkt"]:
                out.append(row)
        try:
            moved = buf.changedGeometries()
        except Exception:
            moved = {}
        for fid, geom in (moved or {}).items():
            try:
                wkt = geom.asWkt()
            except Exception:
                continue
            # A changed geometry is recorded by the id it has in the package, so
            # recovery can put it back on the right feature. If that feature is
            # gone by then the entry is skipped rather than guessed at.
            out.append({"role": role, "what": "moved", "fid": int(fid),
                        "wkt": wkt})

        # What was taken away matters as much as what was put down, and for a
        # while this only recorded what was put down. add_merging, which runs on
        # most brush strokes, deletes the neighbours of the same class and adds
        # one merged polygon in their place; repair, reclassify_at,
        # remove_point_at and settle_edits delete too. Recording the addition
        # and not the deletion meant a restore would put the merged polygon back
        # beside the three it had replaced: the same ground claimed twice, in a
        # program whose first rule is that two marks never share ground.
        try:
            gone = buf.deletedFeatureIds()
        except Exception:
            gone = []
        for fid in (gone or []):
            try:
                fid = int(fid)
            except (TypeError, ValueError):
                continue
            if fid < 0:
                # It was added in this same session and deleted again before any
                # save. It never reached the file, so there is nothing on disk to
                # take away, and the matching "added" row is not written either.
                continue
            out.append({"role": role, "what": "deleted", "fid": fid})

        # And an attribute changed in the buffer: a class renamed across what is
        # drawn, a note written on a frame, a reclassification that changes the
        # name rather than the geometry.
        try:
            edited = buf.changedAttributeValues()
        except Exception:
            edited = {}
        for fid, values in (edited or {}).items():
            try:
                fid = int(fid)
            except (TypeError, ValueError):
                continue
            if fid < 0:
                continue        # it is already carried by its "added" row
            by_name = {}
            for at, value in (values or {}).items():
                try:
                    name = names[int(at)]
                except (IndexError, TypeError, ValueError):
                    continue
                if value is None or _is_null(value):
                    by_name[name] = None
                elif isinstance(value, (int, float, str, bool)):
                    by_name[name] = value
                else:
                    by_name[name] = str(value)
            if by_name:
                out.append({"role": role, "what": "attrs", "fid": fid,
                            "fields": by_name})
        return out

    @staticmethod
    def _wkt(feature):
        try:
            g = feature.geometry()
            return g.asWkt() if g is not None and not g.isNull() else ""
        except Exception:
            return ""

    @staticmethod
    def _fields(feature, names):
        """The attributes, as values a JSON file can hold.

        QGIS does not use None for an empty field: it uses a null QVariant, and
        every feature the brush makes has at least one, because a GeoPackage
        layer exposes its fid and a feature that has never been committed has no
        fid yet. str() of that is the text "<PyQt5.QtCore.QVariant object at
        0x7f...>", and a restore wrote that text back into the column. So a
        value is tested for being null before anything else is done with it.
        """
        out = {}
        for n in names:
            try:
                v = feature[n]
            except Exception:
                continue
            if v is None or _is_null(v):
                continue
            if isinstance(v, (int, float, str, bool)):
                out[n] = v
            else:
                out[n] = str(v)         # a date, most likely
        return out

    def _write(self, text):
        os.makedirs(long_path(self.folder), exist_ok=True)
        tmp = self.path + ".part"
        with io.open(long_path(tmp), "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass                    # a filesystem that cannot: still better
        os.replace(long_path(tmp), long_path(self.path))

    def set_aside(self, how):
        """The buffers this snapshot holds are being emptied by somebody
        else, without a save: QGIS asking "Save the changes?" on the way out
        and being answered Discard, a table taken out of the project with its
        edits in it. From then on nothing is pending, and the next look would
        have deleted the file: the one copy of that work left anywhere.

        So the file is left where it is, with how it was let go of written
        into its first line, and this session takes a new name. A file that
        no running session owns is exactly what the next Open campaign offers
        back, and the session's net starts empty again, so nothing this
        session does from here on can overwrite it or delete it. Returns the
        file, or None when there was nothing to keep."""
        if self.last is None or not os.path.exists(long_path(self.path)):
            return None
        kept = self.path
        try:
            lines = self.last.splitlines()
            head = json.loads(lines[0])
            head["let_go"] = how
            self._write("\n".join([json.dumps(head, ensure_ascii=False)]
                                  + lines[1:]) + "\n")
        except Exception as err:
            # The file as it was is still there, and still kept: only the
            # line saying how it came to be kept is missing.
            log("the recovery file could not be marked: %s" % err)
        self.session = _recovery_session()
        self.last = None
        return kept

    def clear(self):
        """Nothing is pending, so nothing needs saving from a crash."""
        self.last = None
        try:
            if os.path.exists(long_path(self.path)):
                os.remove(long_path(self.path))
        except Exception as err:
            log("the recovery file could not be removed: %s" % err)
        return 0


# ------------------------------------------------------------- reading back
def snapshots_waiting(folder, session="", campaign_id=""):
    """Snapshots in this folder that no running session owns.

    A file belonging to the session asking is not a stray: it is the net, doing
    its job. Anything else was written by a run that ended without saving.

    campaign_id, when given, keeps a snapshot from being offered to the wrong
    campaign. A new campaign made in a folder where an old one was set aside
    would otherwise be handed the old one's unsaved work, which is not a
    recovery but a contamination: the class codes would mean something else.
    """
    where = os.path.join(folder, RECOVERY_FOLDER)
    out = []
    try:
        names = sorted(os.listdir(long_path(where)))
    except OSError:
        return out
    for name in names:
        if not name.endswith(SNAPSHOT_SUFFIX):
            continue
        if session and name == session + SNAPSHOT_SUFFIX:
            continue
        path = os.path.join(where, name)
        head, rows = read_snapshot(path)
        if not rows:
            continue
        if campaign_id and head.get("campaign") and \
                head.get("campaign") != campaign_id:
            log("a recovery file in this folder belongs to another campaign "
                "and was left alone: %s" % os.path.basename(path))
            continue
        out.append((path, head, rows))
    return out


def read_snapshot(path):
    """The header and the entries. A truncated last line is dropped, not fatal:
    a snapshot interrupted mid-write is exactly the case this has to survive."""
    head, rows = {}, []
    try:
        with io.open(long_path(path), encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    log("recovery file %s: line %d is incomplete and was skipped"
                        % (os.path.basename(path), i + 1))
                    continue
                if i == 0 and "program" in item:
                    head = item
                elif "role" in item:
                    rows.append(item)
    except OSError as err:
        log("cannot read_snapshot the recovery file %s: %s" % (path, err))
    return head, rows


def describe_snapshot(head, rows):
    """One readable line about a snapshot, for the question asked at open.

    It counts the kinds separately, because "41 polygons" reads as "41 things
    you drew" and some of those entries are removals. Somebody deciding whether
    to put an afternoon back should be told what putting it back will do.
    """
    per_role, removals, renames = {}, 0, 0
    for r in rows:
        if r.get("what") == "deleted":
            removals += 1
            continue
        if r.get("what") == "attrs":
            renames += 1
            continue
        per_role[r["role"]] = per_role.get(r["role"], 0) + 1
    what = ", ".join("%d %s" % (n, role)
                     for role, n in sorted(per_role.items())) or "nothing drawn"
    if removals:
        what += ", %d removal%s" % (removals, "" if removals == 1 else "s")
    if renames:
        what += ", %d change%s to what was already there" % (
            renames, "" if renames == 1 else "s")
    when = head.get("written", "an unknown time")
    return "%s, drawn up to %s, build %s" % (what, when,
                                             head.get("build", "unknown"))


def keep_snapshot(path, suffix=RESTORED_SUFFIX):
    """Keep a snapshot that has been dealt with, rather than deleting it.

    Called after a restore, with .restored, and after the user says Discard,
    with .discarded. Deleting it would be tidier and would also mean that one
    wrong answer to one question loses the work for good. "Not now" does not
    come here: it leaves the file as it is, to be offered again.
    """
    try:
        target = path + suffix
        n = 1
        while os.path.exists(long_path(target)):
            n += 1
            target = "%s%s.%d" % (path, suffix, n)
        os.replace(long_path(path), long_path(target))
        return target
    except Exception as err:
        log("the recovery file could not be set aside: %s" % err)
        return None


def snapshots_set_aside(folder, campaign_id=""):
    """Snapshots dealt with earlier and kept: (path, how, head, rows).

    how is "restored" for a file whose work was put back and "discarded" for
    one turned down with Discard. Check lists them, because a campaign whose
    recovery folder holds work nobody put back is not "everything on disk",
    however clean its buffers are. A file of RasterLabel 1.0 that said
    .restored after a "Not now" as well is listed the same way, which is why
    the words for it do not promise that its work is in the package."""
    where = os.path.join(folder, RECOVERY_FOLDER)
    out = []
    try:
        names = sorted(os.listdir(long_path(where)))
    except OSError:
        return out
    for name in names:
        rest = name.split(SNAPSHOT_SUFFIX, 1)
        if len(rest) != 2 or not rest[1]:
            continue
        if rest[1].startswith(DISCARDED_SUFFIX):
            how = "discarded"
        elif rest[1].startswith(RESTORED_SUFFIX):
            how = "restored"
        else:
            continue
        path = os.path.join(where, name)
        head, rows = read_snapshot(path)
        if campaign_id and head.get("campaign") and \
                head.get("campaign") != campaign_id:
            continue
        out.append((path, how, head, rows))
    return out
