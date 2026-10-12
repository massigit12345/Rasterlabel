"""rasterlabel.compat

The few places where one QGIS differs from another.
"""

try:
    from qgis.utils import iface
except Exception:          # QGIS is not running: tests, or a script
    iface = None


def run_dialog(dialog):
    """Open a dialog and wait. PyQt5 answers to both exec() and exec_();
    PyQt6, which QGIS 4 is built on, dropped the underscore."""
    runner = getattr(dialog, "exec", None) or getattr(dialog, "exec_")
    return runner()


# What is remembered when QGIS is not there to remember it: the suites, or a
# script run outside QGIS. Kept for the session only. Falling back on a plain
# QSettings instead would write into the registry of whoever runs the tests.
_SETTINGS_HERE = {}


def _settings():
    """QgsSettings when this is QGIS, None otherwise. Imported here and not
    at the top: it is the one QGIS class only this needs, and every fake
    QGIS the suites build would otherwise have to grow it."""
    try:
        from qgis.core import QgsSettings
        return QgsSettings()
    except Exception:
        return None


def read_setting(key, default=None, kind=str):
    """A value QGIS remembers on this machine, or the default.

    QgsSettings hands every value back as text on some platforms, a bool as
    "true", a number as "12.5", so it is turned into the kind asked for here,
    once, rather than at every caller."""
    store = _settings()
    if store is None:
        value = _SETTINGS_HERE.get(key, default)
    else:
        try:
            value = store.value(key, default)
        except Exception:
            value = default
    if value is None:
        return default
    try:
        if kind is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if kind is list:
            if isinstance(value, str):
                return [value] if value else []
            return [str(v) for v in (value or [])]
        return kind(value)
    except (TypeError, ValueError):
        return default


def write_setting(key, value):
    store = _settings()
    if store is None:
        _SETTINGS_HERE[key] = value
        return
    try:
        store.setValue(key, value)
    except Exception:
        pass
