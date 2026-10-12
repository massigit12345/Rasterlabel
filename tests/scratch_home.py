"""A home of its own for a suite, however it is started.

tests/run.py gives its suites a scratch home, because Cutouts writes its log
into the folder of the program, ~/RasterLabel, whenever its default folder,
~/RasterLabel/cutouts, is there. A suite started by hand,
python3 tests/test_x.py, had no such home and appended its lines to the log of
whoever ran it. Every suite imports this module first, so a suite run by hand
gets a scratch home too; under run.py it finds RL_SUITE_HOME set and leaves
the runner's home alone.
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("RL_SUITE_HOME"):
    _home = tempfile.mkdtemp(prefix="rl_suite_home_")
    atexit.register(shutil.rmtree, _home, True)
    # git reads its global settings from the home: keep the real ones.
    _gitconfig = os.path.join(os.path.expanduser("~"), ".gitconfig")
    if "GIT_CONFIG_GLOBAL" not in os.environ and os.path.isfile(_gitconfig):
        os.environ["GIT_CONFIG_GLOBAL"] = _gitconfig
    os.environ["HOME"] = os.environ["USERPROFILE"] = _home
    os.environ["RL_SUITE_HOME"] = _home
