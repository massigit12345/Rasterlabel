"""rasterlabel.launch

Taking the old panel down and putting a new one up.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDockWidget, QScrollArea

from .constants import BUILD, NAME, ONE_COLUMN, qgis_version_text, VERSION
from .compat import iface
from .project import canvas
from .errors import (check_qgis, hook, log, shield_tools, shielded, trouble,
                     warn_old_qgis)
from .widgets import Keys
from .tools import (BoxTool, BrushTool, CutoutTool, LineTool, PointTool,
                    TileTool)
from .panel import Panel
from .processing_provider import processing_register


#  Start
# =====================================================================
# What QGIS saves the place of the dock under. A dock without a name is not
# remembered: it came back, every session, wherever QGIS chose to put it. The
# same name is how one copy of this code finds the panel another copy made.
DOCK_NAME = "RasterLabelDock"


def panel_of_other_copy():
    """The panel already up in this QGIS that this copy of the code did not
    build, or None.

    The plugin and the launcher pasted into the console are two copies of the
    program, each with its own idea of "the panel that is up", and neither
    knew of the other: with the plugin installed, the two lines of the README
    made a second panel, two tools on the same map. The dock is the one thing
    both can see, by its name. A dock with no panel in it is a leftover, and
    is taken away."""
    try:
        found = iface.mainWindow().findChild(QDockWidget, DOCK_NAME)
    except Exception:
        return None
    if found is None:
        return None
    try:
        panel = found.widget().widget()
    except Exception:
        panel = None
    if panel is None:
        try:
            iface.removeDockWidget(found)
            found.deleteLater()
        except Exception:
            pass
        return None
    return found, panel


def listen(keys):
    """Put the key filter on the map again. Qt moves a filter that is already
    installed to the front instead of adding it twice, so this is safe to call
    whenever the panel may have lost it."""
    for w in (canvas(), canvas().viewport()):
        try:
            w.installEventFilter(keys)
        except Exception:
            pass


def shut_down():
    state = globals().get("_RASTERLABEL")
    if not state:
        return
    dock, keys, panel = state
    # Taking the dock away hides it, and a hidden dock is what pressing its X
    # looks like: closed() below would say "nothing was saved or lost, and the
    # campaign is still open" while the plugin was being unloaded, QGIS was
    # closing, or a new panel was taking this one's place. None of that was
    # true then. What happened to the work is said by whatever did it.
    try:
        panel.taken_down = True
    except Exception:
        pass
    try:
        panel.close_module()
    except Exception:
        pass
    # close_module closes the correction with Correct; this is for the one
    # case where closing the module stopped before it got that far, so its
    # layer does not outlive the plugin.
    try:
        panel.close_correction()
    except Exception:
        pass
    # close_module saves what the module was holding, so by now there is
    # normally nothing pending and the snapshot should go. Without this, closing
    # QGIS left a file that the next open read as an afternoon never saved, and
    # putting it back made a second copy of work that was already on disk.
    try:
        panel.keep_safe()
    except Exception as err:
        log("the recovery snapshot was not brought up to date on the way out: "
            "%s" % err)
    try:
        watched = (canvas(), canvas().viewport())
    except Exception as err:
        # canvas() reaches through iface, and this runs while QGIS is taking
        # things down. A failure here must not abort the teardown before the
        # dock is removed and _RASTERLABEL is cleared, which would leave a
        # panel nobody could reach and a second one on the next launch.
        log("the canvas could not be reached while closing: %s" % err)
        watched = ()
    for w in watched:
        try:
            w.removeEventFilter(keys)
        except Exception:
            pass
    # panel.let_go() is what actually undoes them. The old line here tried to
    # disconnect panel.refresh_rasters, which since 3.11 was never what got
    # connected: a wrapper made on the spot was, and a disconnect that does
    # not match fails silently. Which is why the ghost lived.
    try:
        gone = panel.let_go()
        if gone:
            log("the previous panel let go of %d connection%s"
                % (gone, "" if gone == 1 else "s"))
    except Exception as err:
        log("the previous panel would not let go: %s" % err)
    try:
        iface.removeDockWidget(dock)
        dock.deleteLater()
    except Exception:
        pass
    log("the panel is taken down: the plugin is unloaded or reloaded, QGIS "
        "is closing, or a new panel takes its place")
    globals()["_RASTERLABEL"] = None


def start():
    """Build the panel, with the net already under it.

    Everything that can go wrong before there is a panel goes wrong here: a
    QGIS too old, a Qt that has moved a class, a leftover dock from a previous
    run. All of it comes out of the same window as everything else, which is
    the point of having one."""
    shield_tools(LineTool, BrushTool, PointTool, TileTool, CutoutTool, BoxTool)
    known = check_qgis()
    try:
        panel = main()
    except Exception as err:
        trouble(err, "Startup")
        if not known:
            warn_old_qgis()
        raise
    if not known:
        warn_old_qgis()
    return panel


def main():
    if not globals().get("_RASTERLABEL"):
        other = panel_of_other_copy()
        if other is not None:
            # Brought forward, not rebuilt: it holds the campaign and the
            # tools of whoever started it.
            dock, panel = other
            try:
                dock.show()
                dock.raise_()
            except Exception:
                pass
            # Pressing the X of that dock gave the arrow keys back, and
            # showing it again does not take them: whoever built the panel
            # left the filter on it for this.
            try:
                if getattr(panel, "key_filter", None) is not None:
                    listen(panel.key_filter)
            except Exception:
                pass
            log("a panel from another copy of the program is already up, "
                "and is the one in use")
            return panel
    shut_down()
    panel = Panel()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    dock = QDockWidget("%s %s" % (NAME, VERSION))
    dock.setObjectName(DOCK_NAME)
    dock.setWidget(scroll)
    dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                     QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                     QDockWidget.DockWidgetFeature.DockWidgetClosable)
    if ONE_COLUMN:
        # Dropped on the top edge the panel becomes a strip across the window,
        # and on a wide screen that is unusable: refuse the two areas that do
        # it. Left and right are the same bar on the other side, and floating
        # is still allowed, as a bar of its own.
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
    panel.dock = dock
    iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    keys = Keys(panel)
    panel.key_filter = keys
    listen(keys)
    canvas().setFocus()

    def closed(visible):
        """Shutting the panel must put the brush down with it.

        The dock has an X, and pressing it only hides the widget: the map tool
        it handed to the canvas stays active and the arrow keys stay captured,
        so the next click on the map still draws, into a campaign the user
        believes they have just closed, with nothing on screen to say so.

        isHidden tells a closed dock from a tabbed one. Tabbing it behind
        another panel also reports it invisible, and treating that as a close
        would put the brush down every time somebody looked at the Layers panel.
        """
        if getattr(panel, "taken_down", False):
            return
        if visible:
            # brought back after the X: the keys are taken again with it
            listen(keys)
            return
        if not dock.isHidden():
            return
        try:
            if panel.section is not None and hasattr(panel.section,
                                                     "release_tools"):
                panel.section.release_tools()
        except Exception as err:
            log("the panel was closed but the tool would not let go: %s" % err)
        for w in (canvas(), canvas().viewport()):
            try:
                w.removeEventFilter(keys)
            except Exception:
                pass
        log("panel closed: the brush and the arrow keys are given back. "
            "Nothing was saved or lost, and the campaign is still open. "
            "To bring it back: Raster > %s, or its button on the toolbar, "
            "for the plugin; the launcher again for the two lines pasted "
            "into the Python Console." % NAME, loud=True)

    hook(dock, dock.visibilityChanged, shielded(closed, "Closing the panel"))
    globals()["_RASTERLABEL"] = (dock, keys, panel)
    # The toolbox too, for the single file pasted into the console, which
    # has no plugin to do it; the plugin's own registration is left as it is.
    processing_register()
    log("shell %s build %s ready on QGIS %s, four modules. Load a raster, "
        "then New campaign." % (VERSION, BUILD, qgis_version_text()))
    return panel
