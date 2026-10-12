"""rasterlabel.plugin

The thin wrapper QGIS needs to put RasterLabel in its Plugins menu.

It is deliberately thin. Everything it does is call launch.start(), which is the
same function the pasted single file calls, so the plugin and the console are not
two programs that drift apart. What the wrapper owns is only what belongs to
being a plugin: the menu entry, the toolbar button, the provider of the
Processing toolbox, and taking them away again when QGIS unloads it.
"""
import os

# QAction lives in QtGui from Qt 6 on; QGIS 3 offers it there too.
from qgis.PyQt.QtGui import QAction, QIcon

from .constants import BUILD, NAME, VERSION
from .errors import log


class RasterLabelPlugin(object):

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.panel = None

    # --------------------------------------------------------------- QGIS
    def initProcessing(self):       # noqa: N802  (the name QGIS looks for)
        """RasterLabel in the Processing toolbox: Agreement between two
        readings. QGIS calls this before initGui, and again when Processing
        is reloaded; registering twice is harmless (processing_register)."""
        try:
            from .processing_provider import processing_register
            processing_register()
        except Exception as err:
            log("RasterLabel is not in the Processing toolbox: %s" % err)

    def initGui(self):              # noqa: N802  (the name QGIS looks for)
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "icon.svg")
        self.action = QAction(QIcon(icon) if os.path.exists(icon) else QIcon(),
                              "%s: annotate a raster" % NAME,
                              self.iface.mainWindow())
        self.action.setToolTip("%s %s (build %s): draw labels on a raster"
                               % (NAME, VERSION, BUILD))
        self.action.triggered.connect(self.run)
        self.iface.addPluginToRasterMenu(NAME, self.action)
        self.iface.addToolBarIcon(self.action)
        log("%s %s build %s loaded as a plugin. It is under Raster, %s, "
            "and on the toolbar." % (NAME, VERSION, BUILD, NAME))

    def unload(self):
        # The panel goes first. QGIS unloads a plugin by dropping its reference,
        # and a dock left behind with a map tool still active is how a plugin
        # takes the canvas with it on the way out.
        #
        # The panel is taken from launch before it is shut down, because
        # shut_down forgets it, and it is the panel that knows the campaign.
        # Its layers stay in the project, but not in edit mode: an upgrade
        # from the Plugin Manager is an unload, and it would leave the
        # polygons and the frames being edited by a program that was gone.
        panel = None
        try:
            from . import launch
            state = getattr(launch, "_RASTERLABEL", None)
            if state:
                panel = state[2]
            launch.shut_down()
        except Exception as err:
            log("while closing the panel on unload: %s" % err)
        if panel is not None and hasattr(panel, "leave_layers"):
            try:
                panel.leave_layers()
            except Exception as err:
                log("while ending the edit sessions on unload: %s" % err)
        try:
            from .processing_provider import processing_unregister
            processing_unregister()
        except Exception as err:
            log("while taking RasterLabel out of the Processing toolbox: %s"
                % err)
        if self.action is not None:
            try:
                self.iface.removePluginRasterMenu(NAME, self.action)
                self.iface.removeToolBarIcon(self.action)
            except Exception as err:
                log("while taking the menu entry away: %s" % err)
            self.action = None
        self.panel = None

    # --------------------------------------------------------------- us
    def run(self):
        """Put the panel up, or bring it back if it is already there.

        Pressing the button twice must not build two panels, which is exactly
        what the console path had to learn the hard way: start() takes the old
        one down and gives back every signal it was holding before building a
        new one, so this is safe to press at any time."""
        try:
            from .launch import start
            self.panel = start()
        except Exception as err:
            # Not reported again. start() has already opened the window about
            # this very exception and then re-raised so that the caller knows
            # the panel is not there; opening a second window under a second
            # heading reads as two separate failures.
            log("the panel could not be opened: %s" % err)
