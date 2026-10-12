"""rasterlabel.errors

What to do when something goes wrong, and how to say it.
"""
import os
import platform
import sys
import time
import traceback

from osgeo import gdal
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QFontDatabase, QFontInfo
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                                 QFileDialog, QFrame, QLabel, QLayout,
                                 QMessageBox, QPlainTextEdit, QSizePolicy,
                                 QToolButton, QVBoxLayout)
from qgis.core import QgsMessageLog

from .constants import (BUILD, SHAPE, BUILT_FOR, BUILT_FOR_NAME, LEVEL_INFO,
                        LEVEL_WARNING, NAME, PREFIX, qgis_version,
                        qgis_version_text, qt_generation, STORM_SECONDS,
                        TRACE_LINES, TROUBLE_W, VERSION)
from .compat import iface, run_dialog
from .naming import without_home


# Set this in the environment to have every line of the log printed on the
# console as well, inside QGIS too. Outside QGIS, in a test or a script, the
# lines are printed anyway.
DEBUG_VARIABLE = "RASTERLABEL_DEBUG"


def log(msg, loud=False):
    """Into the QGIS message log, and onto the console when there is one.

    Not a bare print: everything this program says when something goes wrong
    would go to stdout, which in QGIS nobody has open. A footprint that could
    not be written, a layer skipped for a mismatched projection, a manifest
    that refused an append would all be invisible. QGIS keeps a log panel for
    exactly this, and a failure belongs there where somebody will trip over
    it.

    loud puts it in the message bar as well, for the ones that change what the
    user is about to get.

    And, once a campaign is open, into a file beside it. The QGIS log panel is
    where a failure belongs while somebody is sitting in front of it; it is not
    where a failure is three days later, when the report arrives and says the
    program "stopped working". A file that outlives the session is the difference
    between a bug report and a shrug.

    The console is the last of these, and inside QGIS it is left out. Inside
    QGIS a print reaches nobody: on Windows there is no console behind the
    window at all, and the message log and the file above already hold every
    line. It is not even harmless. log() is called from the except blocks
    that report a failure, and a print to a console whose encoding cannot
    spell a character of the message (a class named in Greek on a cp1252
    console) would raise a second error out of the code that was reporting
    the first. So the line is printed only where somebody is reading the
    console: outside QGIS, where there is no message log and the console is
    all there is, or when RASTERLABEL_DEBUG is set by somebody who wants it.
    And a print that fails is dropped, never raised."""
    if iface is None or os.environ.get(DEBUG_VARIABLE):
        try:
            print("[%s] %s" % (NAME, msg))
        except (OSError, UnicodeError, ValueError):
            # a console that cannot be written to, or cannot spell the
            # message: the message log and the file still have it
            pass
    try:
        QgsMessageLog.logMessage(str(msg), NAME, LEVEL_INFO)
    except Exception:
        pass
    to_file(msg)
    if loud:
        try:
            iface.messageBar().pushMessage(NAME, str(msg), level=LEVEL_WARNING, duration=7)
        except Exception:
            pass


# Where the log file is, or None. Set by the panel when a campaign opens, which
# is the first moment there is a sensible folder to write into.
_LOG = {"path": None, "complained": False}
LOG_NAME = "rasterlabel.log"
LOG_MAX = 1024 * 1024               # a megabyte, then it is rolled over once


def log_to(folder):
    """Start writing the log beside this campaign. Returns the path, or None."""
    if not folder:
        _LOG["path"] = None
        return None
    try:
        path = os.path.join(folder, LOG_NAME)
        _LOG["path"] = path
        _LOG["complained"] = False
        to_file("---- %s %s build %s, log opened on QGIS %s"
                % (NAME, VERSION, BUILD, qgis_version_text()))
        return path
    except Exception:
        _LOG["path"] = None
        return None


def to_file(msg):
    """Append one line. Never raises, and never says so twice.

    A read only folder, a full disk, a OneDrive lock: all of them are reasons the
    log cannot be written, and none of them is a reason to interrupt somebody who
    is drawing. The first failure is reported through the other channels and then
    the file is given up on for this campaign.
    """
    path = _LOG.get("path")
    if not path:
        return
    try:
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
            old = path + ".1"
            try:
                if os.path.exists(old):
                    os.remove(old)
                os.replace(path, old)
            except Exception:
                pass
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                   without_home(msg)))
    except Exception as err:
        if not _LOG["complained"]:
            _LOG["complained"] = True
            _LOG["path"] = None
            try:
                QgsMessageLog.logMessage(
                    "the log file cannot be written, so nothing will be kept "
                    "for a report: %s" % err, NAME, LEVEL_WARNING)
            except Exception:
                pass


def log_path():
    return _LOG.get("path")


def environment():
    """Everything a report needs to be worth reading: the versions."""
    rows = [("RasterLabel", "%s build %s, as a %s (built for QGIS %d.%d %s)"
             % (VERSION, BUILD, SHAPE, BUILT_FOR[0], BUILT_FOR[1],
                BUILT_FOR_NAME))]
    try:
        rows.append(("QGIS", qgis_version_text()))
    except Exception:
        rows.append(("QGIS", "unknown"))
    try:
        from qgis.PyQt.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        rows.append(("Qt", "%s, PyQt %s" % (QT_VERSION_STR, PYQT_VERSION_STR)))
    except Exception:
        pass
    try:
        rows.append(("GDAL", gdal.VersionInfo("RELEASE_NAME")))
    except Exception:
        pass
    try:
        import numpy
        rows.append(("numpy", numpy.__version__))
    except Exception:
        pass
    rows.append(("Python", sys.version.split()[0]))
    # Windows 11 still calls itself Windows 10 to most of what asks. Python
    # before 3.12 passes that on, so a report from Windows 11 under the Python
    # of an older QGIS would say "Windows 10". The build number is the only thing
    # that tells them apart: 22000 is the first build of Windows 11.
    system, release = platform.system(), platform.release()
    build = platform.version().split(".")
    if (system == "Windows" and release == "10" and len(build) > 2
            and build[2].isdigit() and int(build[2]) >= 22000):
        release = "11"
    rows.append(("system", "%s %s" % (system, release)))
    return rows


def error_text(err):
    """The message, lowercased, with the errno spelled out when there is one.

    A PermissionError prints as 'Permission denied' on one platform and as
    'Accesso negato' on an Italian Windows, and neither string can be matched
    on. The number behind it is the same everywhere, so it is put in front of
    the text where the rules can see it, and the name of the class is put
    after it: a MemoryError says 'Unable to allocate 41.2 GiB' and never the
    word memory, but it is still called MemoryError in every language."""
    bits = []
    number = getattr(err, "errno", None)
    if number is not None:
        bits.append("errno %s" % number)
    bits.append(str(err))
    bits.append(type(err).__name__)
    return " ".join(bits).lower()

#  Each rule: a list of words that all have to appear, a word that must not,
#  the plain sentence, and what to try. The sentence never claims certainty
#  about a thing it cannot see.
TROUBLE_RULES = [
    (["older than the"], None,
     "This QGIS is older than the one the plugin was written on.",
     ["The plugin is built for QGIS %d.%d %s and newer. Most of it works on "
      "an older one; what breaks is a call QGIS has since renamed, and it "
      "breaks the first time you press that particular button."
      % (BUILT_FOR[0], BUILT_FOR[1], BUILT_FOR_NAME),
      "Updating QGIS is the clean answer. The long term release is the safe "
      "one to move to.",
      "If you cannot update, carry on and see: this window will say exactly "
      "which call is missing the moment one is, and that is usually a small "
      "thing to fix."]),
    (["database is locked"], None,
     "The campaign package is being held open by something else.",
     ["In the QGIS Layers panel, look for a layer of this campaign with a "
      "pencil on it and turn editing off: an open edit session holds the "
      "whole package.",
      "Close any second QGIS, DB Browser for SQLite, or file browser that has "
      "the same .gpkg open.",
      "If the campaign sits in OneDrive, Dropbox or a network share, pause the "
      "sync or move it to a local disk. SQLite locks and cloud folders do not "
      "get along.",
      "Then press Save again. Nothing drawn has been lost: it is still in the "
      "layer, only the write did not land."]),
    (["errno 13"], None,
     "The system refused permission to write that file.",
     ["The file is probably open in another program. Close it there and try "
      "again.",
      "If it is in Program Files, a system folder, or a folder owned by "
      "another user, pick somewhere else: Folder in the Cutouts bar, or the "
      "campaign folder itself.",
      "Some antivirus software locks a file for a few seconds after it is "
      "written. Waiting and repeating the same command usually works."]),
    (["permission denied"], None,
     "The system refused permission to write that file.",
     ["The file is probably open in another program. Close it there and try "
      "again.",
      "Choose an output folder you own: your Desktop or Documents always "
      "works, Program Files never does."]),
    (["errno 28"], None,
     "The disk is full.",
     ["Free some room and repeat the command: what had already been written "
      "was removed, so there is no half file left behind.",
      "A whole raster at full resolution costs roughly width x height x bands "
      "bytes. The scale box under Whole raster brings that down by the square "
      "of what you set.",
      "Cutouts writes into the folder shown in the panel. Press Folder to see "
      "where that is, and pick a roomier disk if it is the wrong one."]),
    (["no space left"], None,
     "The disk is full.",
     ["Free some room and repeat the command.",
      "Or write somewhere else: the Folder button in Cutouts, the file chooser "
      "in Whole raster."]),
    (["errno 2"], None,
     "That file is not where it was.",
     ["The raster or the campaign package has been moved, renamed, or is on a "
      "drive that is not plugged in.",
      "If it lives in OneDrive and shows a cloud icon, it is online only. "
      "Right click it, Always keep on this device, wait for the tick, and try "
      "again.",
      "Reopen the campaign from where it actually is: Open in the campaign "
      "bar."]),
    (["no such file"], None,
     "That file is not where it was.",
     ["It has been moved, renamed, or lives on a drive that is not connected.",
      "Reopen the campaign from its present place, or reload the raster."]),
    (["memory"], None,
     "There was not enough memory for an image that size.",
     ["Use the scale under Whole raster. A half scale needs a quarter of the "
      "memory.",
      "Work frame by frame instead: with tiles drawn, Cutouts writes them one "
      "at a time and never holds the whole raster.",
      "Close the rasters you are not using. QGIS keeps their overviews in "
      "memory too.",
      "A 32 bit QGIS cannot address more than about 2 GB whatever the machine "
      "has. Check Help, About: if it says 32 bit, that is the ceiling."]),
    (["not recognized as being in a supported file format"], None,
     "GDAL does not know how to read that file.",
     ["The file may be damaged, or only partly downloaded.",
      "A .tif written by another program is sometimes a BigTIFF or holds a "
      "compression this GDAL build has no licence for. Open it in QGIS first: "
      "if QGIS cannot draw it either, it is the file.",
      "Converting it once with Raster, Conversion, Translate usually settles "
      "it."]),
    (["does not support creat"], None,
     "This GDAL build cannot write that format.",
     ["Choose GeoTIFF in the format dropdown. Every GDAL can write it.",
      "PNG and JPEG are written by copying a GeoTIFF, so they need both "
      "drivers. If one is missing, GeoTIFF alone still works."]),
    (["has been deleted"], None,
     "Something the panel was holding has been closed underneath it.",
     ["A layer was removed from the project, or the panel itself was closed "
      "and the old one is still being spoken to.",
      "Close the panel and start it again: Raster > RasterLabel for the "
      "plugin, or the two lines of the launcher in the Python Console. The "
      "campaign is on disk, nothing is lost by restarting.",
      "If a layer of the campaign was removed by hand, reopen the campaign "
      "and it will be put back."]),
    (["qgis", "no attribute"], None,
     "This QGIS is missing something the plugin expects.",
     ["Almost always an older QGIS than the plugin was built for. The "
      "versions are in the detail below: if yours is the smaller number, that "
      "is the whole story.",
      "The plugin is written for QGIS %d.%d %s and newer. On an older one, "
      "most of it works and this one call does not."
      % (BUILT_FOR[0], BUILT_FOR[1], BUILT_FOR_NAME),
      "Copy the report and it can be made to work on your version: it is "
      "usually one renamed call."]),
    (["no attribute", "qgs"], None,
     "This QGIS is missing something the plugin expects.",
     ["Almost always an older QGIS than the plugin was built for. The "
      "versions are in the detail below.",
      "The plugin is written for QGIS %d.%d %s and newer."
      % (BUILT_FOR[0], BUILT_FOR[1], BUILT_FOR_NAME),
      "Copy the report: on an older QGIS this is usually one renamed call, "
      "and it can be taught both names."]),
    (["no module named", "osgeo"], None,
     "GDAL is not on this Python.",
     ["Run it inside QGIS, as a plugin or from the QGIS Python Console, not "
      "from a system Python or an IDE. Only QGIS's own Python has osgeo on "
      "it.",
      "Install it as a plugin, from its zip, or open Plugins > Python "
      "Console and paste the two lines of the launcher."]),
    (["no module named"], None,
     "A library the plugin needs is not on this Python.",
     ["Run it inside QGIS, as a plugin or from its Python Console: QGIS "
      "ships with everything this needs.",
      "If it already is the QGIS console, the install is incomplete. "
      "Reinstalling QGIS from the official installer puts it back."]),
    (["disk i/o error"], None,
     "SQLite could not read or write the package.",
     ["A network drive or a synced folder is the usual cause. Copy the "
      "campaign folder to a local disk and open it from there.",
      "If it happens on a local disk, the file may be damaged. Open the .gpkg "
      "in QGIS: if the layers draw, copy them into a new campaign."]),
    (["malformed"], None,
     "The package does not read as a GeoPackage any more.",
     ["Look in the campaign folder for a file ending in -wal or -shm and "
      "leave it there: those hold the most recent writes and deleting them "
      "loses work.",
      "Copy the whole folder somewhere safe before trying anything else.",
      "Then open the .gpkg in QGIS by itself. If its layers draw, a new "
      "campaign can be filled from them."]),
    (["crs"], ["no attribute"],
     "The projections do not agree.",
     ["The raster may have no CRS at all. Right click it, Properties, Source, "
      "and set the one it should have.",
      "A campaign is tied to the grid of the raster it was made on. A raster "
      "in another projection has to be reprojected first: Raster, Projections, "
      "Warp.",
      "The drawing CRS and the measuring CRS are both written in the log line "
      "the panel prints when a module opens."]),
    (["read-only", "layer"], None,
     "The layer will not accept a change.",
     ["The package may be open read only because another program has it. "
      "Close that one and reopen the campaign.",
      "Or the file itself is marked read only on disk. In its Properties, "
      "clear the read only tick."]),
]


def diagnose(err, what):
    """From an exception to a sentence and a few things to try.

    what is the thing the user asked for, in their words: 'Save', 'Cut',
    'Whole raster'. It goes in the headline because 'something failed' is not
    a sentence anybody can act on."""
    text = error_text(err)      # the class name is already in there
    for must, mustnt, sentence, remedies in TROUBLE_RULES:
        if all(word in text for word in must):
            if mustnt and any(word in text for word in mustnt):
                continue
            return sentence, list(remedies)
    return ("%s stopped with an error that has no advice written for it yet."
            % what,
            ["The message underneath is the machine's own words, and is "
             "usually the fastest way in.",
             "Nothing already saved is affected: a failure here leaves the "
             "campaign as it was before the command.",
             "Press Copy report and send it on. A report with the versions in "
             "it is enough to find this without the file."])


def fixed_font():
    """A font whose letters are all one width, for reports whose columns
    line up: Consolas where Windows has it, the system's own otherwise, at
    the size of the rest of the window."""
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.TypeWriter)
    if not QFontInfo(f).fixedPitch():
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    try:
        f.setPointSizeF(QApplication.font().pointSizeF())
    except Exception:
        pass
    return f



class Trouble(QDialog):
    """The window that opens when a command fails.

    Three parts, in the order a person needs them: what was being done and
    what went wrong, then what to try, then the detail, folded away. The
    detail is the part nobody reads and everybody needs the moment they ask
    somebody else for help, so it goes on the clipboard with one button."""

    def __init__(self, err, what, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s: %s did not finish" % (NAME, what))
        sentence, remedies = diagnose(err, what)
        self.report = self.build_report(err, what, sentence)

        box = QVBoxLayout(self)
        box.setSpacing(10)
        # A word wrapped label is as tall as the width it is given, and Qt
        # only asks when the layout is told to. Without this the dialog is
        # sized for one line of each paragraph and the advice is cut in half,
        # which of all the things to lose is the worst one.
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        headline = self.paragraph(sentence)
        f = QFont(headline.font())
        f.setBold(True)
        headline.setFont(f)
        box.addWidget(headline)

        said = self.paragraph("%s: %s" % (type(err).__name__, err))
        said.setObjectName("quiet")
        box.addWidget(said)

        box.addWidget(self.rule())
        try_this = QLabel("What to try")
        f2 = QFont(try_this.font())
        f2.setBold(True)
        try_this.setFont(f2)
        box.addWidget(try_this)
        for i, remedy in enumerate(remedies, 1):
            box.addWidget(self.paragraph("%d.  %s" % (i, remedy)))

        self.fold = QToolButton()
        self.fold.setText(" Detail")
        self.fold.setCheckable(True)
        self.fold.setArrowType(Qt.ArrowType.RightArrow)
        self.fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.fold.setAutoRaise(True)
        self.fold.toggled.connect(self.show_detail)
        box.addWidget(self.fold)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlainText(self.report)
        self.detail.setMinimumHeight(220)
        self.detail.setMinimumWidth(TROUBLE_W)
        # In the fixed font of the system, as the Check report is, and
        # wrapped: paths and the traceback were cut off at the right edge.
        try:
            self.detail.setFont(fixed_font())
        except Exception:
            pass
        self.detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.detail.hide()
        box.addWidget(self.detail)

        buttons = QDialogButtonBox()
        copy = buttons.addButton("Copy report", QDialogButtonBox.ButtonRole.ActionRole)
        copy.setToolTip("Put the whole report on the clipboard, versions and\n"
                        "traceback included, ready to paste into a message.")
        copy.clicked.connect(self.copy_report)
        save = buttons.addButton("Save report...", QDialogButtonBox.ButtonRole.ActionRole)
        save.setToolTip("Write the report to a text file.")
        save.clicked.connect(self.save_report)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        box.addWidget(buttons)

    def paragraph(self, words):
        """A label that wraps, and that says how tall it needs to be.

        Qt will not work the second part out on its own: a wrapped label
        reports the height of a single line unless its size policy is told
        that height depends on width, and then the dialog is built around a
        sentence and clips the other four."""
        label = QLabel(words)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        policy = label.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)
        label.setSizePolicy(policy)
        # The width is pinned here rather than on the dialog, because a layout
        # under SetMinimumSize decides the dialog's minimum itself and would
        # throw any width set from outside away.
        label.setMinimumWidth(TROUBLE_W)
        label.setMinimumHeight(label.heightForWidth(TROUBLE_W))
        return label

    def rule(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setProperty("rule", True)
        return line

    def build_report(self, err, what, sentence):
        lines = ["%s %s build %s: %s did not finish"
                 % (NAME, VERSION, BUILD, what),
                 "",
                 "reading: %s" % sentence,
                 "%s: %s" % (type(err).__name__, err),
                 ""]
        for name, value in environment():
            lines.append("%-12s %s" % (name, value))
        lines.append("")
        lines.append("when: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("")
        trace = traceback.format_exc()
        if not trace or trace.strip() == "NoneType: None":
            trace = "".join(traceback.format_exception_only(type(err), err))
        rows = trace.splitlines()
        if len(rows) > TRACE_LINES:
            rows = (rows[:4] + ["   ... %d lines left out ..."
                                % (len(rows) - TRACE_LINES)]
                    + rows[-(TRACE_LINES - 5):])
        lines.extend(rows)
        # pasted into public issues, as the Check report is
        return without_home("\n".join(lines))

    def show_detail(self, opened):
        self.fold.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        self.detail.setVisible(opened)
        self.adjustSize()

    def copy_report(self):
        try:
            QApplication.clipboard().setText(self.report)
            log("report copied to the clipboard")
        except Exception as err:
            log("could not reach the clipboard: %s" % err)

    def save_report(self):
        where = os.path.join(
            os.path.expanduser("~"),
            "%s_report_%s.txt" % (PREFIX, time.strftime("%Y%m%d_%H%M%S")))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the report", where, "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.report)
            log("report written to %s" % path, loud=True)
        except Exception as err:
            log("the report itself could not be written: %s" % err, loud=True)

_TROUBLE = {"open": False, "signature": None, "when": 0.0}


def in_a_storm(err, what):
    """True when this exact failure has just been shown."""
    signature = (what, type(err).__name__, str(err)[:200])
    now = time.time()
    if _TROUBLE["open"]:
        return True
    if (_TROUBLE["signature"] == signature
            and now - _TROUBLE["when"] < STORM_SECONDS):
        return True
    _TROUBLE["signature"] = signature
    _TROUBLE["when"] = now
    return False


def is_ghost(err):
    """A call that arrived from a panel that no longer exists.

    Qt deletes the widget and leaves the Python object holding the connection,
    so a leftover from an earlier launch answers a signal and finds its own
    window gone. It reads as an error and is not one: there is nothing for the
    user to do about a thing that is already dead."""
    return isinstance(err, RuntimeError) and "has been deleted" in str(err)


def trouble(err, what, parent=None):
    """Log it, then put it in front of the user with something to try.

    Never raises. A reporter that can fail is a reporter that turns one bug
    into two, and the second one has nowhere to be reported."""
    try:
        log("%s failed: %s: %s" % (what, type(err).__name__, err))
        log(traceback.format_exc())
    except Exception:
        pass
    # A ghost gets a line, not a window. Versions 3.11 to 3.13 leave one
    # behind at every relaunch, and this function is reached even by their
    # code, because the console runs every version in the same namespace: so
    # this is also where their ghosts are put to rest.
    if is_ghost(err):
        try:
            log("%s came from a panel of an earlier launch and was ignored. "
                "Restart QGIS once to be rid of it for good." % what,
                loud=True)
        except Exception:
            pass
        return
    try:
        if in_a_storm(err, what):
            log("%s failed again: %s" % (what, err), loud=True)
            return
    except Exception:
        pass
    try:
        _TROUBLE["open"] = True
        window = Trouble(err, what, parent or window_of_qgis())
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        run_dialog(window)
    except Exception:
        # The window itself could not be built: say it where something will
        # still be read, and carry on.
        try:
            QMessageBox.critical(None, NAME, "%s did not finish.\n\n%s: %s"
                                 % (what, type(err).__name__, err))
        except Exception:
            try:
                print("[%s] %s failed: %s" % (NAME, what, err))
            except Exception:
                # no console either: the log still has it
                log("%s failed: %s" % (what, err))
    finally:
        _TROUBLE["open"] = False
        _TROUBLE["when"] = time.time()


def window_of_qgis():
    try:
        return iface.mainWindow()
    except Exception:
        return None


def hook(owner, signal, handler):
    """Connect, and write down the connection so that it can be undone.

    A signal that belongs to the project, to the canvas or to a layer outlives
    the panel that listened to it. Qt does not mind: it keeps calling. So a
    second launch would leave the first panel still listening to layersAdded,
    and the first thing that added a layer would reach into a window whose C++
    side had been deleted an hour earlier. The Python object is still there,
    holding the connection alive; only the widget underneath is gone.

    Undoing a connection needs the very object that was connected, and since
    3.11 that object is a fresh wrapper made on the spot: disconnecting the
    bare method could never match it, and failed silently every time. It is
    remembered here instead."""
    signal.connect(handler)
    owner.__dict__.setdefault("_hooks", []).append((signal, handler))
    return handler


_OWN_HANDS = [0]


class own_hands(object):
    """A rollback or a removal of layers that RasterLabel does itself, on
    purpose: the No of its own "Save before closing?", a frame that could not
    be written taken back, a package let go of before it is moved.

    The panel listens for buffers emptied without a save, so that the recovery
    file of the work in them is kept instead of deleted, and it must be able to
    tell those apart from its own: QGIS asking "Save the changes?" on the way
    out and being told Discard looks, from a layer, exactly like the close
    without saving that was asked for here."""

    def __enter__(self):
        _OWN_HANDS[0] += 1
        return self

    def __exit__(self, *exc):
        _OWN_HANDS[0] -= 1
        return False


def by_own_hands():
    return _OWN_HANDS[0] > 0


def unhook(owner):
    """Let go of everything hook() wrote down. Never raises: this runs while
    something is already being taken apart."""
    gone = 0
    for signal, handler in owner.__dict__.pop("_hooks", []):
        try:
            signal.disconnect(handler)
            gone += 1
        except Exception:
            pass
    return gone


def alive(obj):
    """Whether the C++ side of a Qt object is still there.

    sip knows; without sip the question is asked of the object itself, and a
    dead one answers with the RuntimeError we are looking for."""
    if obj is None:
        return True                     # nothing to outlive
    try:
        from qgis.PyQt import sip
        return not sip.isdeleted(obj)
    except Exception:
        pass
    try:
        obj.objectName()
        return True
    except RuntimeError:
        return False
    except Exception:
        return True


def room_for(slot):
    """How many positional arguments this slot will actually take.

    None means as many as you like: the slot has a *args, or it is something
    whose signature cannot be read, and in both cases nothing has to be
    trimmed."""
    try:
        import inspect
        params = list(inspect.signature(slot).parameters.values())
    except (TypeError, ValueError, ImportError):
        return None
    for p in params:
        if p.kind == p.VAR_POSITIONAL:
            return None
    return sum(1 for p in params
               if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))


def shielded(slot, what):
    """The same slot, with the error window behind it.

    Every button in every bar is connected through this. A command that
    raises would otherwise leave a traceback in the log panel and a user
    looking at a button that did nothing.

    The arguments are cut down to what the slot can hold, and that is not a
    nicety: it is what keeps every button working.
    clicked carries a bool. Connect a bound method that takes none and PyQt
    reads its signature and drops the bool for you; put a plain function with
    *args in between and PyQt sees something that will take anything, hands
    over the bool, and every command in the program dies on
    'takes 1 positional argument but 2 were given'. So the signature is read
    here instead, exactly where PyQt stopped being able to read it."""
    fits = room_for(slot)
    owner = getattr(slot, "__self__", None)

    def run(*args, **kwargs):
        # A leftover from a previous launch is not a failure to report: it is
        # a ghost, and the only right thing to do with it is nothing.
        if owner is not None and not alive(owner):
            log("%s ignored: it belongs to a panel that is gone" % what)
            return None
        try:
            return slot(*(args if fits is None else args[:fits]), **kwargs)
        except Exception as err:
            trouble(err, what)
    run.__name__ = getattr(slot, "__name__", "slot")
    run.wrapped = slot
    run.room = fits
    return run


def shield_tools(*classes):
    """Put the same net under what the mouse does on the canvas.

    A map tool that raises inside canvasPressEvent takes the exception into
    Qt, which prints it and carries on with the tool half through whatever it
    was doing. Wrapping the four entry points keeps that where it can be
    seen."""
    for cls in classes:
        for name in ("canvasPressEvent", "canvasMoveEvent",
                     "canvasReleaseEvent", "canvasDoubleClickEvent",
                     "keyPressEvent"):
            original = getattr(cls, name, None)
            if original is None or getattr(original, "shielded", False):
                continue
            wrapped = tool_net(original, cls.__name__, name)
            setattr(cls, name, wrapped)


def tool_net(original, tool_name, event_name):
    what = "%s (%s)" % (tool_name.replace("Tool", ""), event_name
                        .replace("canvas", "").replace("Event", "").lower())

    def run(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        except Exception as err:
            trouble(err, what)
    run.shielded = True
    run.__name__ = event_name
    return run


def check_qgis():
    """Say, once, whether this QGIS is one the plugin knows.

    Older than what it was built on is allowed: most of it will work, and a
    refusal helps nobody who cannot upgrade today. But it is said out loud
    before the first thing goes wrong, because an unexplained failure two
    hours later is much worse than a warning now."""
    version = qgis_version()
    if version >= BUILT_FOR:
        log("QGIS %s, Qt %d: known ground" % (qgis_version_text(),
                                              qt_generation() or 5))
        return True
    if version == (0, 0):
        log("this QGIS does not say which version it is; carrying on")
        return True
    log("QGIS %s is older than the %d.%d %s this was built for"
        % (qgis_version_text(), BUILT_FOR[0], BUILT_FOR[1], BUILT_FOR_NAME),
        loud=True)
    return False


class OldQgis(Exception):
    """Raised only to be shown: it carries the version mismatch into the same
    window everything else uses, so there is one place where problems appear
    and not two."""
    pass


def warn_old_qgis():
    err = OldQgis(
        "QGIS %s is older than the %d.%d %s this plugin was written on."
        % (qgis_version_text(), BUILT_FOR[0], BUILT_FOR[1], BUILT_FOR_NAME))
    trouble(err, "Startup")
