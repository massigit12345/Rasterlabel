# RasterLabel, a QGIS panel for drawing labels on a raster.
# Copyright (C) 2026 Massimiliano Guastella
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. It is distributed WITHOUT ANY WARRANTY; see LICENSE.
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""RasterLabel: a QGIS panel for drawing labels on a raster.

Two ways in, one body of code.

As a plugin, QGIS imports this package and calls classFactory below. As a script,
the single file built by tools/bundle.py is pasted into the Python Console and
calls start() at its last line. Both end up in launch.start(), so there is no
second path to go wrong.

Nothing happens at import. That is deliberate: a plugin that builds widgets while
QGIS is still starting is a plugin that fails on somebody else's machine for
reasons nobody can reproduce.
"""

__all__ = ["classFactory", "VERSION", "BUILD"]


def classFactory(iface):            # noqa: N802  (the name QGIS looks for)
    """What QGIS calls to load the plugin."""
    from .plugin import RasterLabelPlugin
    return RasterLabelPlugin(iface)


def __getattr__(name):
    """VERSION and BUILD without importing the world to read them."""
    if name in ("VERSION", "BUILD"):
        from . import constants
        return getattr(constants, name)
    raise AttributeError(name)
