"""Rewrite the three addresses QGIS shows for the plugin, if the repository
ever moves.

    python3 tools/set_urls.py <github-account>
    python3 tools/set_urls.py <github-account> --repo Rasterlabel
    python3 tools/set_urls.py --show

tracker, repository and homepage in rasterlabel/metadata.txt already point at
the repository, and they are not decorative: QGIS prints them in Manage and
Install Plugins, plugins.qgis.org requires them and checks that they open, and
the tracker is where a bug report goes. So when the repository is renamed or
moves to another account, all three have to move with it, together, and the
zip has to be rebuilt from the new metadata.txt. That is all this does, it
says exactly what it changed, and it can be run twice without harm.

--show prints the three as they stand and changes nothing.

It was first written for the other direction. metadata.txt used to ship with
REPLACE-ME in those fields, tools/package_plugin.py refused to build a release
zip while they were unfilled, and the continuous integration run carried an
exemption so that a zip could still be made for the install suite. This script
filled the addresses in and then took that exemption out. Both of those are
done: the addresses are real and the exemption is gone from the workflow. The
code that removes it is still here because it costs nothing when there is
nothing to remove, and it says so. package_plugin still refuses a placeholder,
so one that finds its way back in is caught at the next build.

--repo defaults to the name repository= in metadata.txt already uses, so
moving to another account keeps the spelling it has, and running this twice
changes nothing the second time. Only when that field holds no GitHub address
does it fall back to 'rasterlabel'. GitHub treats the name without regard to
case, so 'rasterlabel' and 'Rasterlabel' reach the same place, but pass --repo
with the spelling you want written into metadata.txt.
"""
import argparse
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = os.path.join(ROOT, "rasterlabel", "metadata.txt")
CI = os.path.join(ROOT, ".github", "workflows", "tests.yml")
FIELDS = ("tracker", "repository", "homepage")

# The lift in the CI run, exactly as package_plugin's refusal describes it. It
# is removed only once the addresses are real; before that, taking it out would
# only make every build fail at the same step.
LIFT = """        env:
          # The builder refuses to make a release zip while metadata.txt still
          # has REPLACE-ME in its tracker and repository URLs, because QGIS shows
          # those to everybody. Here the point is only that the zip can be built,
          # so the refusal is lifted; it still bites when a release is cut.
          RL_ALLOW_PLACEHOLDERS: '1'
"""


def read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def current():
    out = {}
    for line in read(META).splitlines():
        for field in FIELDS:
            if line.startswith(field + "="):
                out[field] = line.split("=", 1)[1].strip()
    return out


def repo_now(now):
    """The repository name repository= already uses, or 'rasterlabel'."""
    m = re.match(r"^https?://github\.com/[^/]+/([^/\s]+?)(?:\.git)?/?$",
                 now.get("repository", ""))
    return m.group(1) if m else "rasterlabel"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("account", nargs="?",
                    help="the GitHub account the plugin will live under")
    ap.add_argument("--repo", default=None,
                    help="the repository name; by default the one "
                         "metadata.txt already uses")
    ap.add_argument("--show", action="store_true",
                    help="print the three addresses as they stand and stop")
    args = ap.parse_args()

    now = current()
    if args.show or not args.account:
        for field in FIELDS:
            print("  %-11s %s" % (field, now.get(field, "(absent)")))
        if any("REPLACE-ME" in v for v in now.values()):
            print()
            print("Still placeholders. Run:  python3 tools/set_urls.py "
                  "<github-account>")
        if not args.account and not args.show:
            return 2
        return 0

    account = args.account.strip().strip("/")
    if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$", account):
        raise SystemExit("'%s' is not a GitHub account name: letters, digits "
                         "and hyphens, not starting or ending with a hyphen."
                         % account)
    base = "https://github.com/%s/%s" % (account, args.repo or repo_now(now))
    wanted = {"tracker": base + "/issues", "repository": base, "homepage": base}

    text = read(META)
    changed = []
    for field, value in wanted.items():
        new = re.sub(r"^%s=.*$" % field, "%s=%s" % (field, value), text,
                     count=1, flags=re.M)
        if new != text:
            changed.append("%s=%s" % (field, value))
            text = new
    if changed:
        write(META, text)
        print("rasterlabel/metadata.txt:")
        for line in changed:
            print("  " + line)
    else:
        print("rasterlabel/metadata.txt already says that; nothing changed.")

    # And only now the lift, because package_plugin would refuse without it
    # while the addresses were still placeholders.
    if os.path.exists(CI):
        ci = read(CI)
        if LIFT in ci:
            write(CI, ci.replace(LIFT, ""))
            print(".github/workflows/tests.yml:")
            print("  the placeholder exemption is gone, so a build that "
                  "reintroduces one now fails")
        else:
            print(".github/workflows/tests.yml: no exemption to remove")

    print()
    for step in (["bundle.py"], ["package_plugin.py"]):
        out = subprocess.run([sys.executable, os.path.join(HERE, step[0])],
                             capture_output=True, text=True, cwd=ROOT)
        print((out.stdout + out.stderr).strip())
        if out.returncode:
            raise SystemExit("rebuilding failed, so nothing was released")
    print()
    # The zip just built comes from a folder with uncommitted edits in it, and
    # package_plugin has said so: it is not the one to attach to a release.
    print("Done. Commit metadata.txt, the workflow and dist/, then build the "
          "release zip with:  python3 tools/package_plugin.py --release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
