"""Rendu 2D explicite d'un nuage de points : ne pas dépendre du rendu par défaut de QGIS (qui peut se limiter à l'emprise en pointillé rouge)."""
from qgis.core import QgsColorRampShader, QgsPointCloudAttributeByRampRenderer, QgsPointCloudClassifiedRenderer, QgsStyle


def apply_default_renderer(layer):
    """Classification si présente, sinon rampe sur Z. Retourne le type de rendu appliqué."""
    names = [a.name() for a in layer.attributes().attributes()]
    if 'Classification' in names:
        layer.setRenderer(QgsPointCloudClassifiedRenderer('Classification', QgsPointCloudClassifiedRenderer.defaultCategories()))
        layer.triggerRepaint()
        return 'classification'
    stats = layer.statistics()
    low, high = stats.minimum('Z'), stats.maximum('Z')
    if low != low or high != high or low >= high:
        low, high = 0.0, 1.0
    renderer = QgsPointCloudAttributeByRampRenderer()
    renderer.setAttribute('Z')
    shader = QgsColorRampShader(low, high, QgsStyle.defaultStyle().colorRamp('Turbo'))
    shader.classifyColorRamp(5)
    renderer.setColorRampShader(shader)
    renderer.setMinimum(low)
    renderer.setMaximum(high)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return 'rampe Z'
