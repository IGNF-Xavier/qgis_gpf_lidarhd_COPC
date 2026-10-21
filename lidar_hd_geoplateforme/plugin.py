from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication
from .provider import Provider

MENU = 'Vues 3D LiDAR'


class Plugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.panel = None
        self.action = None

    def initGui(self):
        self.provider = Provider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        self.action = QAction(MENU, self.iface.mainWindow())
        self.action.triggered.connect(self.show_panel)
        self.iface.addPluginToMenu('&LiDAR HD Géoplateforme', self.action)

    def show_panel(self):
        if self.panel is None:
            from .views3d import ViewsPanel
            self.panel = ViewsPanel(self.iface)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.panel)
        self.panel.show()
        self.panel.raise_()

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        if self.action:
            self.iface.removePluginMenu('&LiDAR HD Géoplateforme', self.action)
            self.action = None
        if self.panel:
            self.panel.close_all()
            self.iface.removeDockWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None
