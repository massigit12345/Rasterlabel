"""The STAC documents RasterLabel writes, held against the published schemas.

The schemas of the label (v1.0.1) and projection (v1.1.0) extensions are
kept beside this file (see NOTICE), because a build server is offline. They
are read with jsonschema when that is installed. When it is not, which is
the case of every QGIS on the desk this was written on, they are read with
the small reader below: the part of JSON Schema draft-07 those two schemas
use (type, enum, const, required, properties, patternProperties,
additionalProperties, items, contains, minItems, maxItems, minLength,
minimum, maximum, allOf, anyOf, oneOf, if/then/else, and $ref inside the
document), so a suite is never skipped for want of a package. A $ref to
another document is a failure here, not a pass: the fields that would need
one (proj:projjson, proj:geometry) are fields RasterLabel does not write.

    errors = validate(item, "label")       # [] when it holds
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = {"label": "label-v1.0.1-schema.json",
           "projection": "projection-v1.1.0-schema.json"}


def schema(name):
    with open(os.path.join(HERE, SCHEMAS[name]), encoding="utf-8") as fh:
        return json.load(fh)


def _is(kind, v):
    if kind == "object":
        return isinstance(v, dict)
    if kind == "array":
        return isinstance(v, list)
    if kind == "string":
        return isinstance(v, str)
    if kind == "integer":
        return (isinstance(v, int) and not isinstance(v, bool)) or (
            isinstance(v, float) and v.is_integer())
    if kind == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if kind == "boolean":
        return isinstance(v, bool)
    if kind == "null":
        return v is None
    raise ValueError("type %r is not known here" % kind)


def _resolve(root, ref):
    if not ref.startswith("#"):
        raise ValueError("a $ref to another document (%s) cannot be read "
                         "offline" % ref)
    node = root
    for part in [p for p in ref[1:].split("/") if p]:
        node = node[part]
    return node


def _check(root, s, v, where, out):
    if s is True or s == {}:
        return
    if s is False:
        out.append("%s: nothing is allowed here" % where)
        return
    if "$ref" in s:
        _check(root, _resolve(root, s["$ref"]), v, where, out)
    if "type" in s:
        kinds = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is(k, v) for k in kinds):
            out.append("%s: %r is not %s" % (where, v, " or ".join(kinds)))
            return
    if "enum" in s and v not in s["enum"]:
        out.append("%s: %r is not one of %r" % (where, v, s["enum"]))
    if "const" in s and v != s["const"]:
        out.append("%s: %r is not %r" % (where, v, s["const"]))
    if isinstance(v, str) and "minLength" in s and len(v) < s["minLength"]:
        out.append("%s: shorter than %d" % (where, s["minLength"]))
    if _is("number", v):
        if "minimum" in s and v < s["minimum"]:
            out.append("%s: %r below %r" % (where, v, s["minimum"]))
        if "maximum" in s and v > s["maximum"]:
            out.append("%s: %r above %r" % (where, v, s["maximum"]))
    if isinstance(v, dict):
        for key in s.get("required") or []:
            if key not in v:
                out.append("%s: %r is required" % (where, key))
        props = s.get("properties") or {}
        patterns = s.get("patternProperties") or {}
        for key, value in v.items():
            matched = False
            if key in props:
                matched = True
                _check(root, props[key], value, "%s.%s" % (where, key), out)
            for pat, sub in patterns.items():
                if re.search(pat, key):
                    matched = True
                    _check(root, sub, value, "%s.%s" % (where, key), out)
            if not matched and "additionalProperties" in s:
                _check(root, s["additionalProperties"], value,
                       "%s.%s" % (where, key), out)
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            out.append("%s: fewer than %d items" % (where, s["minItems"]))
        if "maxItems" in s and len(v) > s["maxItems"]:
            out.append("%s: more than %d items" % (where, s["maxItems"]))
        if isinstance(s.get("items"), dict):
            for i, item in enumerate(v):
                _check(root, s["items"], item, "%s[%d]" % (where, i), out)
        if "contains" in s and not any(
                not _errors(root, s["contains"], item) for item in v):
            out.append("%s: no item is %r" % (where, s["contains"]))
    for sub in s.get("allOf") or []:
        _check(root, sub, v, where, out)
    if "anyOf" in s and not any(not _errors(root, sub, v)
                                for sub in s["anyOf"]):
        out.append("%s: none of anyOf holds" % where)
    if "oneOf" in s:
        held = [sub for sub in s["oneOf"] if not _errors(root, sub, v)]
        if len(held) != 1:
            out.append("%s: %d of oneOf hold, not 1" % (where, len(held)))
    if "if" in s:
        branch = "then" if not _errors(root, s["if"], v) else "else"
        if branch in s:
            _check(root, s[branch], v, where, out)


def _errors(root, s, v):
    out = []
    _check(root, s, v, "$", out)
    return out


def validate(document, name):
    """The ways the document breaks the named schema; [] when it holds."""
    root = schema(name)
    try:
        import jsonschema
    except ImportError:
        return _errors(root, root, document)
    validator = jsonschema.Draft7Validator(root)
    return [e.message for e in validator.iter_errors(document)]


def reader():
    """Which reader validate() uses, said once by a suite."""
    try:
        import jsonschema
        return "jsonschema %s" % getattr(jsonschema, "__version__", "")
    except ImportError:
        return "the reader in minischema.py (jsonschema is not installed)"
