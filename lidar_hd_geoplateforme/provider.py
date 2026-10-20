from qgis.core import QgsProcessingProvider
from .algorithms import ListEditionsAlgorithm,ExtractEditionsAlgorithm
class Provider(QgsProcessingProvider):
    def id(self): return 'lidarhd_geoplateforme'
    def name(self): return 'LiDAR HD Géoplateforme'
    def longName(self): return self.name()
    def loadAlgorithms(self):
        self.addAlgorithm(ListEditionsAlgorithm()); self.addAlgorithm(ExtractEditionsAlgorithm())
