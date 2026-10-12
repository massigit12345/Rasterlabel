"""The release zip says when it is not the commit.

tools/package_plugin.py zips the folder on disk. Before the fix, a scratch file
left in rasterlabel/, or an edit not yet committed, went into the zip with
nothing said, and the zip attached to a release could hold code no commit has.

This clones the repository (so the clone is exactly one commit), then dirties
it three ways and checks the builder says so each time, that --release
refuses, and that a development build is told in one line. It needs git and
a repository to clone, and says so and stops when either is missing.

    python3 tests/test_package_from_commit.py
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
fails = []

if shutil.which("git") is None or not os.path.exists(os.path.join(SRC, ".git")):
    print("git or the repository is not here, so there is nothing to clone: "
          "skipped")
    sys.exit(0)


def check(what, ok, detail=""):
    print("  %s  %s%s" % ("ok  " if ok else "FAIL", what,
                          ("   [%s]" % detail) if (detail and not ok) else ""))
    if not ok:
        fails.append(what)


work = tempfile.mkdtemp()
clone = os.path.join(work, "clone")
# safe.directory, because a checkout owned by another account (a build
# server's, an administrator's) is refused by git otherwise
subprocess.run(["git", "-c", "safe.directory=*", "clone", "-q", SRC, clone],
               check=True)
# The tool under test is the one in the source folder, committed or not.
shutil.copy(os.path.join(SRC, "tools", "package_plugin.py"),
            os.path.join(clone, "tools", "package_plugin.py"))
subprocess.run(["git", "-C", clone, "update-index", "--assume-unchanged",
                "tools/package_plugin.py"], check=True)


def build(*extra, env=None):
    e = dict(os.environ)
    e.pop("RL_DEV_BUILD", None)
    e.pop("RL_ALLOW_PLACEHOLDERS", None)
    e.update(env or {})
    return subprocess.run([sys.executable, os.path.join(clone, "tools",
                                                         "package_plugin.py")]
                          + list(extra), capture_output=True, text=True,
                          cwd=clone, env=e)


print("a clean clone")
out = build()
check("builds", out.returncode == 0, out.stderr)
check("and says nothing is amiss", "NOT COMMIT" not in out.stderr, out.stderr)
check("and names the commit", "exactly commit" in out.stdout, out.stdout)
out = build("--release")
check("--release builds it too", out.returncode == 0, out.stderr)

print("a scratch file nobody committed")
scratch = os.path.join(clone, "rasterlabel", "scratch_notes.txt")
open(scratch, "w").write("not for release\n")
out = build()
check("still builds", out.returncode == 0, out.stderr)
check("and it is in the zip, as before", "rasterlabel/scratch_notes.txt" in
      zipfile.ZipFile(os.path.join(clone, "dist", [f for f in os.listdir(
          os.path.join(clone, "dist")) if f.endswith(".zip")][0])).namelist())
check("but the builder says the zip is not the commit",
      "NOT COMMIT" in out.stderr, out.stderr)
check("and names the file", "rasterlabel/scratch_notes.txt" in out.stderr,
      out.stderr)
out = build("--release")
check("--release refuses", out.returncode != 0, out.stdout)
check("and says why", "scratch_notes.txt" in (out.stderr + out.stdout))
out = build(env={"RL_DEV_BUILD": "1"})
check("a development build gets one line, not the block",
      "NOT COMMIT" not in out.stderr and "development build" in out.stdout,
      out.stdout + out.stderr)
os.remove(scratch)

print("a file .gitignore hides, which git status would not mention")
with open(os.path.join(clone, ".git", "info", "exclude"), "a") as fh:
    fh.write("rasterlabel/hidden.py\n")
hidden = os.path.join(clone, "rasterlabel", "hidden.py")
open(hidden, "w").write("x = 1\n")
out = build()
check("is named all the same", "rasterlabel/hidden.py" in out.stderr,
      out.stderr)
os.remove(hidden)

print("an edit not committed")
meta = os.path.join(clone, "rasterlabel", "metadata.txt")
with open(meta, "a") as fh:
    fh.write("\n# an edit\n")
out = build()
check("is named", "edited" in out.stderr and "metadata.txt" in out.stderr,
      out.stderr)
check("--release refuses", build("--release").returncode != 0)

shutil.rmtree(work, ignore_errors=True)
print()
print("FAILED: %d" % len(fails) if fails else "all pass")
sys.exit(1 if fails else 0)
