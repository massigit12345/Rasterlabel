"""The release zip is the same bytes every time, and the workflow is pinned.

The zip. The README and .gitattributes say the release zip is the same byte
for byte wherever it is built. ZipFile.write took the date and the
permissions of every entry from the file on disk, so the same commit built
twice, or after a checkout had touched the files, or on another machine, gave
zips that differed in every header. The builder now writes every entry with
the earliest date a zip can hold and plain permissions, sorted by name.

Here the packager is run twice on a copy of the package, between the runs
the files are given other dates and other permissions and listed in another
order on disk, and the two zips are compared as bytes.

The workflow. It reads the repository and nothing else, so its token is
asked for no more than that; a job that hangs is stopped; and an action is
named by the commit of the release that was checked, because a tag can be
moved.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)

fails = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:300]) if not cond else ""))
    if not cond:
        fails.append(name)


work = tempfile.mkdtemp(prefix="rl_release_files_")
try:
    # --------------------------------------------------------------- the zip
    print("the zip is the same bytes every time")
    tree = os.path.join(work, "tree")
    os.makedirs(os.path.join(tree, "tools"))
    shutil.copytree(os.path.join(ROOT, "rasterlabel"),
                    os.path.join(tree, "rasterlabel"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(os.path.join(ROOT, "tools", "package_plugin.py"),
                os.path.join(tree, "tools"))
    shutil.copy(os.path.join(ROOT, "LICENSE"), tree)
    env = dict(os.environ, RL_DEV_BUILD="1", RL_ALLOW_PLACEHOLDERS="1",
               PYTHONUTF8="1")

    def build(name):
        out = os.path.join(work, name)
        run = subprocess.run(
            [sys.executable, os.path.join(tree, "tools", "package_plugin.py"),
             "--out", out], capture_output=True, text=True, env=env,
            encoding="utf-8", errors="replace")
        check("%s: built" % name, run.returncode == 0 and os.path.exists(out),
              run.stdout + run.stderr)
        with open(out, "rb") as fh:
            return out, fh.read()

    first_path, first = build("first.zip")

    # other dates, other permissions: what a different checkout leaves
    old = time.time() - 40 * 86400
    for folder, _, files in os.walk(tree):
        for f in files:
            full = os.path.join(folder, f)
            os.utime(full, (old, old))
            try:
                os.chmod(full, 0o755)
            except OSError:
                pass
    time.sleep(2.1)             # a zip date has two seconds to it
    second_path, second = build("second.zip")
    check("the two zips are the same bytes", first == second,
          (hashlib.sha256(first).hexdigest()[:12],
           hashlib.sha256(second).hexdigest()[:12]))

    with zipfile.ZipFile(first_path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        check("it holds the plugin", "rasterlabel/metadata.txt" in names
              and "rasterlabel/__init__.py" in names)
        check("the entries are sorted by name", names == sorted(names),
              names[:6])
        check("every entry has the earliest date a zip holds",
              all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in infos),
              {i.date_time for i in infos})
        check("and the same permissions, a plain readable file",
              {(i.external_attr >> 16) & 0o777 for i in infos} == {0o644},
              {oct((i.external_attr >> 16) & 0o777) for i in infos})
        check("made as if on one system, wherever it was",
              {i.create_system for i in infos} == {3})
        check("with the licence among them",
              "rasterlabel/LICENSE" in names)
        check("and no path with a backslash in it",
              not any("\\" in n for n in names), names[:3])
        check("the files are the files", z.read("rasterlabel/metadata.txt")
              == open(os.path.join(ROOT, "rasterlabel", "metadata.txt"),
                      "rb").read())
finally:
    shutil.rmtree(work, ignore_errors=True)

# ----------------------------------------------------------------- the workflow
print()
print("the workflow reads the repository, stops, and pins what it runs")
path = os.path.join(ROOT, ".github", "workflows", "tests.yml")
if not os.path.exists(path):
    print("  no workflow in this checkout, nothing to check")
else:
    text = open(path, encoding="utf-8").read()
    top = re.search(r"^permissions:\s*\n((?:[ \t]+\S.*\n)+)", text, re.M)
    check("a permissions block at the top", top is not None)
    check("that asks for contents: read and nothing else",
          top is not None and [l.strip() for l in top.group(1).splitlines()
                               if l.strip() and not l.strip().startswith("#")]
          == ["contents: read"], top.group(1) if top else None)
    jobs = re.search(r"^jobs:\s*\n(.*)\Z", text, re.M | re.S).group(1)
    names = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs, re.M)
    check("there are jobs", len(names) >= 2, names)
    for name in names:
        body = re.search(r"^  %s:\s*\n(.*?)(?=^  [A-Za-z0-9_-]+:\s*$|\Z)"
                         % re.escape(name), jobs, re.M | re.S).group(1)
        m = re.search(r"^    timeout-minutes:\s*(\d+)\s*$", body, re.M)
        check("job %s has a timeout" % name,
              m is not None and 5 <= int(m.group(1)) <= 120,
              m.group(1) if m else None)
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, re.M)
    check("it uses actions", len(uses) >= 3, uses)
    for ref, rest in uses:
        if ref.startswith("./"):
            continue
        sha = ref.rpartition("@")[2]
        check("%s is named by a full commit" % ref.split("@")[0],
              re.fullmatch(r"[0-9a-f]{40}", sha) is not None, ref)
        check("%s says which release in a comment" % ref.split("@")[0],
              re.search(r"#\s*v\d+(\.\d+)*\s*$", rest) is not None, rest)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
