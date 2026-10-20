from qgis.core import QgsApplication
from .provider import Provider
class Plugin:
    def __init__(self, iface): self.provider=None
    def initGui(self):
        self.provider=Provider(); QgsApplication.processingRegistry().addProvider(self.provider)
    def unload(self):
        if self.provider: QgsApplication.processingRegistry().removeProvider(self.provider); self.provider=None
