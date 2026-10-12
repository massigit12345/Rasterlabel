"""rasterlabel.view

Moving and zooming the map.
"""
from qgis.core import QgsPointXY, QgsRectangle

from .constants import LONG_STEP, ZOOM_FACTOR
from .project import canvas


#  Navigation
# =====================================================================
def step(dx, dy, percent, long_step=False):
    c = canvas()
    e = c.extent()
    f = percent / 100.0 * (LONG_STEP if long_step else 1)
    p = c.center()
    c.setCenter(QgsPointXY(p.x() + dx * e.width() * f, p.y() + dy * e.height() * f))
    c.refresh()


def zoom(inwards):
    c = canvas()
    factor = 1.0 / ZOOM_FACTOR if inwards else ZOOM_FACTOR
    try:
        c.zoomByFactor(factor)
    except Exception:
        e = c.extent()
        w, h = e.width() * factor / 2.0, e.height() * factor / 2.0
        p = c.center()
        c.setExtent(QgsRectangle(p.x() - w, p.y() - h, p.x() + w, p.y() + h))
    c.refresh()
