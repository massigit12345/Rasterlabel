"""CITATION.cff and .zenodo.json: well formed, and the same facts as the code.

A reviewer who wants to cite the program reads these two files, GitHub reads
the first and Zenodo the second, and each is a place where a number goes
stale unnoticed. So, with no YAML library (a small reader of the few shapes
the file uses is written below, and the file is kept to them):

- CITATION.cff: cff-version 1.2.0, a message, the title RasterLabel, the
  version 1.1 the program says it is (constants.VERSION and metadata.txt),
  the release date the CHANGELOG gives it, type software, one author with
  family-names, given-names, an ORCID whose check digit holds and an
  affiliation, the licence
  the code carries (SPDX-License-Identifier in the package, and the GNU GPL
  version 2 text of LICENSE), repository-code copied from metadata.txt, an
  abstract of one paragraph, keywords;
- no DOI and no identifiers in either file until Zenodo has given one: what
  is not known is left out, never filled in with a placeholder, and no
  placeholder word survives anywhere in them;
- .zenodo.json: upload_type software, the same title, version, creator (with
  the same ORCID and affiliation), licence and keywords, a description that is
  the abstract, no DOI.

Needs nothing but Python (every Python in tests/run.py runs it).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:500]) if not cond and detail != "" else ""))
    if not cond:
        fails.append(name)


def text_of(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def scalar(word):
    word = word.strip()
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "\"'":
        return word[1:-1]
    return word


def parse_cff(text):
    """The few shapes CITATION.cff uses: key: scalar; key: >- followed by an
    indented paragraph; key: followed by '- scalar' items or by '- key:
    value' items of a mapping."""
    out, lines, i = {}, text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s+(.*))?$", line)
        if not m:
            raise ValueError("line %d is not a key: %r" % (i + 1, line))
        key, rest = m.group(1), (m.group(2) or "").strip()
        i += 1
        if rest in (">-", ">", "|", "|-"):
            body = []
            while i < len(lines) and (lines[i].startswith("  ")
                                      or not lines[i].strip()):
                body.append(lines[i].strip())
                i += 1
            out[key] = (" " if rest.startswith(">") else "\n").join(
                body).strip()
        elif rest:
            out[key] = scalar(rest)
        else:
            items = []
            while i < len(lines) and (lines[i].startswith("  ")
                                      or not lines[i].strip()):
                row = lines[i]
                i += 1
                if not row.strip():
                    continue
                if row.lstrip().startswith("- "):
                    body = row.lstrip()[2:]
                    kv = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s+(.*)$", body)
                    items.append({kv.group(1): scalar(kv.group(2))}
                                 if kv else scalar(body))
                else:
                    kv = re.match(r"^\s+([A-Za-z][A-Za-z0-9_-]*):\s+(.*)$",
                                  row)
                    if kv and items and isinstance(items[-1], dict):
                        items[-1][kv.group(1)] = scalar(kv.group(2))
                    else:
                        raise ValueError("cannot read %r" % row)
            out[key] = items
    return out


def flat(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


cff_text = text_of("CITATION.cff")
zen_text = text_of(".zenodo.json")
cff = parse_cff(cff_text)
zen = json.loads(zen_text)

print("CITATION.cff")
check("cff-version 1.2.0", cff.get("cff-version") == "1.2.0",
      cff.get("cff-version"))
for key in ("message", "title", "authors", "version", "type", "abstract"):
    check("%s is there" % key, bool(cff.get(key)), sorted(cff))
check("the title is RasterLabel", cff["title"] == "RasterLabel")
check("type software", cff["type"] == "software")
authors = cff["authors"]
check("one author, with family-names, given-names, orcid and affiliation",
      len(authors) == 1
      and set(authors[0]) == {"family-names", "given-names", "orcid",
                              "affiliation"}
      and authors[0]["family-names"] == "Guastella"
      and authors[0]["given-names"] == "Massimiliano", authors)


def orcid_ok(text):
    """An ORCID iD as https://orcid.org/xxxx-xxxx-xxxx-xxxx, its last
    character the ISO 7064 11,2 check digit of the other fifteen."""
    m = re.match(r"^(?:https://orcid\.org/)?(\d{4})-(\d{4})-(\d{4})-(\d{3})"
                 r"([\dX])$", text or "")
    if not m:
        return False
    total = 0
    for ch in "".join(m.groups()[:4]):
        total = (total + int(ch)) * 2
    digit = (12 - total % 11) % 11
    return m.group(5) == ("X" if digit == 10 else str(digit))


orcid = authors[0].get("orcid", "") if authors else ""
check("the ORCID is written as a link and its check digit holds",
      orcid.startswith("https://orcid.org/") and orcid_ok(orcid), orcid)
check("the affiliation is written out",
      len(authors[0].get("affiliation", "")) > 20 if authors else False)
changelog = text_of("CHANGELOG.md")
released = re.search(r"^## 1\.1, (\d{4}-\d{2}-\d{2})", changelog, re.M)
check("date-released is the date the CHANGELOG gives 1.1",
      released is not None
      and cff.get("date-released") == released.group(1),
      (cff.get("date-released"), released and released.group(1)))
constants = text_of("rasterlabel", "constants.py")
metadata = text_of("rasterlabel", "metadata.txt")
version = re.search(r'^VERSION = "([^"]+)"', constants, re.M).group(1)
check("the version is 1.1, the one the program says",
      cff["version"] == "1.1" == version, (cff["version"], version))
check("and the one metadata.txt says",
      re.search(r"^version=(\S+)", metadata, re.M).group(1) == cff["version"])
init = text_of("rasterlabel", "__init__.py")
spdx = re.search(r"SPDX-License-Identifier:\s*(\S+)", init).group(1)
check("the licence is the one the code carries: %s" % spdx,
      cff["license"] == spdx, (cff["license"], spdx))
licence = text_of("LICENSE")
check("and LICENSE is the GNU GPL, version 2",
      "GNU GENERAL PUBLIC LICENSE" in licence and "Version 2, June 1991"
      in licence)
repo = re.search(r"^repository=(\S+)", metadata, re.M)
check("repository-code is the repository of metadata.txt",
      repo is not None and cff.get("repository-code") == repo.group(1),
      (cff.get("repository-code"), repo and repo.group(1)))
check("the abstract is one paragraph of some length",
      "\n" not in cff["abstract"] and 400 < len(cff["abstract"]) < 2400,
      len(cff["abstract"]))
check("and a few keywords", len(cff.get("keywords", [])) >= 3,
      cff.get("keywords"))
for key in ("doi", "identifiers", "url"):
    check("no %s: it is not known, so it is left out" % key,
          key not in cff and not re.search(r"^\s*%s\s*:" % key, cff_text,
                                           re.M))
check("no later version is named (the 1.2.0 of cff-version is the format's)",
      not re.search(r"\b1\.[2-9]\b|next release|future version|upcoming",
                    re.sub(r"^cff-version:.*$", "", cff_text, flags=re.M),
                    re.I))

print()
print(".zenodo.json")
check("upload_type software", zen.get("upload_type") == "software")
check("the same title and version", zen.get("title") == cff["title"]
      and zen.get("version") == cff["version"], (zen.get("title"),
                                                 zen.get("version")))
check("one creator, with the name, ORCID and affiliation of the author",
      zen.get("creators") == [{
          "name": "Guastella, Massimiliano",
          "affiliation": authors[0].get("affiliation") if authors else None,
          "orcid": orcid.replace("https://orcid.org/", "")}],
      zen.get("creators"))
check("the same licence, written as Zenodo's lower case SPDX identifier",
      zen.get("license") == cff["license"].lower(), zen.get("license"))
check("the description is the abstract", flat(zen.get("description", ""))
      == flat(cff["abstract"]))
check("the same keywords", sorted(zen.get("keywords", []))
      == sorted(cff.get("keywords", [])))
check("open access", zen.get("access_right") == "open")
check("the repository, as a related identifier of kind url",
      zen.get("related_identifiers") == [{
          "identifier": cff["repository-code"],
          "relation": "isSupplementTo", "scheme": "url"}],
      zen.get("related_identifiers"))
for key in ("doi", "prereserve_doi"):
    check("no %s anywhere" % key, '"%s"' % key not in zen_text)
check("no later version is named", not re.search(
    r"\b1\.[2-9]\b|next release|future version|upcoming", zen_text, re.I))

print()
print("neither file holds a placeholder")
placeholder = re.compile(
    r"TODO|FIXME|XXX|TBD|CHANGEME|lorem|placeholder|your[ _-]?name|"
    r"0000-0000|10\.\d{4,9}/|example\.(org|com)|<[^>/]*(name|doi)[^>]*>",
    re.I)
# put together from pieces, so that this file does not match what it looks for
personal = re.compile("|".join([r"(?<![A-Za-z])[A-Za-z]:" + r"[\\/]",
                                "/" + "home" + "/", "/" + "Users" + "/"]))
for name, text in (("CITATION.cff", cff_text), (".zenodo.json", zen_text)):
    found = placeholder.findall(text)
    check("%s has none" % name, not found, found)
    check("%s has no path of anybody's machine" % name,
          not personal.search(text))
    check("%s ends with one newline, in LF" % name,
          text.endswith("\n") and not text.endswith("\n\n")
          and "\r" not in text)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
