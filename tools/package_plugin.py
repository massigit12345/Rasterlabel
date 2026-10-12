"""Make the zip QGIS installs.

QGIS installs a plugin from a zip that holds exactly one folder, named after the
plugin, with metadata.txt and __init__.py at its top. So that is what comes out:
dist/rasterlabel-<version>.zip, with the package inside it and nothing else. No
tests, no tools, no dist, no __pycache__, because a plugin zip that carries its own
test suite is a plugin zip that takes four times as long to download for no reason.

    python3 tools/package_plugin.py              # the folder as it stands
    python3 tools/package_plugin.py --release    # the last commit, or nothing

The same files always make the same zip, byte for byte: every entry has the
same date and permissions and the entries are sorted by name, so the zip of a
tag can be checked by building it again.

It refuses to build a zip that QGIS would reject, and it checks the two things
QGIS checks first: that metadata.txt is there with a version in it, and that the
folder inside the zip is named the same as the plugin.

It zips the folder as it stands on disk, not the commit, because that is what
the suites need: they install the zip of the code they are testing, committed
or not. A release is the other case. The zip attached to a release has to be
exactly the commit it is tagged on, and a stray scratch file in rasterlabel/,
or an edit not yet committed, would otherwise go out inside it with nothing to
say so. So the builder asks git how the files it is about to zip differ from
the last commit and says so, loudly, in a block nobody can scroll past. With
--release it refuses instead. RL_DEV_BUILD=1 says the zip is for yourself and
shortens the warning to one line; tests/run.py sets RL_ALLOW_PLACEHOLDERS for
the same purpose, and that counts as a development build too.
"""
import argparse
import ast
import io
import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAME = "rasterlabel"
PKG = os.path.join(ROOT, NAME)

# What goes in: the modules, the metadata, the icon, and the licence, because a
# plugin that does not carry its own licence is a plugin nobody may redistribute.
WANTED_SUFFIX = (".py", ".txt", ".svg", ".png")
SKIP_DIRS = {"__pycache__", ".git", "tests", "tools", "dist"}


def version_of():
    for node in ast.parse(io.open(os.path.join(PKG, "constants.py"),
                                  encoding="utf-8").read()).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "VERSION":
                    return node.value.value
    raise SystemExit("no VERSION in rasterlabel/constants.py")


def metadata_version():
    path = os.path.join(PKG, "metadata.txt")
    if not os.path.exists(path):
        raise SystemExit("rasterlabel/metadata.txt is missing: QGIS will not "
                         "install the plugin without it")
    for line in io.open(path, encoding="utf-8"):
        if line.strip().startswith("version="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("metadata.txt has no version=")


def unfilled():
    """Placeholders still in metadata.txt.

    QGIS shows tracker, repository and homepage to everybody who looks at the
    plugin, and the tracker is where a bug report goes. A release zip that ships
    with REPLACE-ME in them tells every user that nobody is listening, and it is
    the kind of thing that is invisible until it is public.
    """
    path = os.path.join(PKG, "metadata.txt")
    bad = []
    for line in io.open(path, encoding="utf-8"):
        if "REPLACE-ME" in line or "example.com" in line:
            bad.append(line.strip())
    return bad


def chosen_files():
    """Every file that goes into the zip, as (path on disk, path in the zip).

    One list, used both to write the zip and to compare it with git, so the
    comparison is of exactly what ships and not of a second guess at it.
    """
    chosen = []
    for folder, dirs, files in os.walk(PKG):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if not f.endswith(WANTED_SUFFIX):
                continue
            full = os.path.join(folder, f)
            chosen.append((full, os.path.join(NAME, os.path.relpath(full, PKG))))
    licence = os.path.join(ROOT, "LICENSE")
    if os.path.exists(licence):
        chosen.append((licence, os.path.join(NAME, "LICENSE")))
    return chosen


# The date every entry of the zip carries, and the permissions: the earliest
# date a zip can hold, and a plain readable file. ZipFile.write takes both
# from the file on disk, so the same commit built twice, or on two machines,
# or after a checkout touched the files, gave two zips that differed in every
# header although every file in them was the same.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ZIP_MODE = 0o100644 << 16


def write_zip(out, chosen):
    """Write the zip: the entries sorted by their name in it, each with the
    fixed date and permissions above, the same compression and no extra
    fields, so that the same files always make the same bytes."""
    entries = sorted((inside.replace(os.sep, "/"), full)
                     for full, inside in chosen)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        for inside, full in entries:
            info = zipfile.ZipInfo(inside, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3          # as if made on Unix, wherever it was
            info.external_attr = ZIP_MODE
            with open(full, "rb") as fh:
                z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED, 9)
    return len(entries)


def git(*args):
    """Run git in the repository and give back what it printed, or None if git
    is not there, this is not a checkout, or git said no. A zip can be built
    from a folder that came out of an archive, with no git at all; the builder
    then has nothing to compare with and says that, rather than failing."""
    try:
        out = subprocess.run(("git",) + args, cwd=ROOT, capture_output=True,
                             text=True)
    except OSError:
        return None
    if out.returncode:
        return None
    return out.stdout


def differs_from_commit(chosen):
    """How what is about to be zipped differs from the last commit.

    Gives back (commit, lines), with lines empty when the zip will be exactly
    the commit, or (None, None) when git cannot say. There are three ways for
    the two to differ. A file going in that was never committed: an untracked
    scratch module, or one that .gitignore hides, which `git status` would not
    even mention, so the list of what ships is compared with `git ls-files`
    rather than asking git what is new. A committed file edited since. And a
    committed file deleted since, which the commit has and the zip will not.
    Line endings alone do not count: git compares through core.autocrlf, so a
    checkout with CRLF on disk is still the commit.
    """
    head = git("rev-parse", "--short", "HEAD")
    tracked = git("ls-files", "-z", "--", NAME, "LICENSE")
    changed = git("diff", "--name-status", "-z", "--no-renames", "HEAD", "--",
                  NAME, "LICENSE")
    if head is None or tracked is None or changed is None:
        return None, None
    tracked = set(p for p in tracked.split("\0") if p)
    lines = set()
    for full, _inside in chosen:
        rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
        if rel not in tracked:
            lines.add("not committed  %s" % rel)
    # --name-status -z gives the status and the path as separate fields, and
    # --no-renames keeps it to exactly two per file.
    fields = [f for f in changed.split("\0") if f]
    for status, path in zip(fields[0::2], fields[1::2]):
        if path != "LICENSE" and not path.endswith(WANTED_SUFFIX):
            continue
        what = "deleted" if status.startswith("D") else "edited"
        lines.add("%-13s  %s" % (what, path))
    return head.strip(), sorted(lines)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", action="store_true",
                    help="refuse to build unless the zip will be exactly the "
                         "last commit")
    ap.add_argument("--out", help="write the zip here instead of in dist/ "
                                  "(the suites use it)")
    args = ap.parse_args()

    code = version_of()
    stated = metadata_version()
    if code != stated:
        # One of these ends up in the QGIS plugin list and the other in every bug
        # report. They have to be the same number.
        raise SystemExit("constants.py says version %s and metadata.txt says %s: "
                         "make them agree before building" % (code, stated))
    blank = unfilled()
    if blank and not os.environ.get("RL_ALLOW_PLACEHOLDERS"):
        raise SystemExit(
            "metadata.txt still has placeholders, and QGIS shows these to "
            "everybody:\n  " + "\n  ".join(blank)
            + "\n\nPut the real addresses in, or set RL_ALLOW_PLACEHOLDERS=1 to "
              "build a zip for yourself anyway.")

    chosen = chosen_files()
    commit, drift = differs_from_commit(chosen)
    dev = bool(os.environ.get("RL_DEV_BUILD")
               or os.environ.get("RL_ALLOW_PLACEHOLDERS"))
    if args.release and commit is None:
        raise SystemExit("--release needs git to say which commit this is, and "
                         "it cannot here, so no zip was built")
    if args.release and drift:
        raise SystemExit(
            "--release: the folder is not commit %s, so no zip was built:\n  "
            % commit + "\n  ".join(drift)
            + "\n\nCommit or remove these, or build from a fresh clone.")

    out = args.out or os.path.join(ROOT, "dist", "%s-%s.zip" % (NAME, code))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    count = write_zip(out, chosen)
    names = zipfile.ZipFile(out).namelist()
    if not any(n == NAME + "/metadata.txt" for n in names):
        raise SystemExit("the zip has no %s/metadata.txt, so QGIS would refuse it"
                         % NAME)
    if not any(n == NAME + "/__init__.py" for n in names):
        raise SystemExit("the zip has no %s/__init__.py, so QGIS would refuse it"
                         % NAME)
    print("%s: %d files, %.0f KB" % (out, count, os.path.getsize(out) / 1024.0))
    if commit is None:
        print("git could not say which commit this is, so nothing says whether "
              "this zip is one")
    elif not drift:
        print("exactly commit %s" % commit)
    elif dev:
        print("a development build: %d file(s) differ from commit %s"
              % (len(drift), commit))
    else:
        # stderr, and a block, because this is the one message that matters
        # when a release is being cut and the easiest one to miss.
        bar = "!" * 72
        sys.stderr.write(
            "\n%s\nTHIS ZIP IS NOT COMMIT %s. It holds the working folder, "
            "and these differ:\n  %s\n\nDo not attach it to a release. "
            "Commit or remove them, or build from\na fresh clone. --release "
            "refuses outright; RL_DEV_BUILD=1 says it is only for you.\n%s\n"
            % (bar, commit, "\n  ".join(drift), bar))
    print("install it with Plugins, Manage and Install Plugins, Install from ZIP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
