# RasterLabel. Open this file in the QGIS Python Console editor and press Run,
# or paste the two lines at the bottom into the console yourself.
#
# It works out where it is, so it keeps working if you move the whole folder,
# and it loads dist/rasterlabel.py, which is the package folded into one file.
# Running it again after a change needs no restart: the panel that is already
# there is taken down first and every signal it was holding is given back.
# A panel made by the installed plugin is not this file's to take down: it is
# brought forward and used, so the plugin and this file never put up two.
#
# Installing it as a plugin instead is Plugins, Manage and Install Plugins,
# Install from ZIP, with the zip from dist/. Either way it is the same program.
import os

try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # The console editor sometimes runs a buffer that has no file name of its
    # own. Put the folder in by hand on the next line if that happens.
    here = r"C:\path\to\rasterlabel"

p = os.path.join(here, "dist", "rasterlabel.py")
exec(compile(open(p, encoding="utf-8").read(), p, "exec"))
