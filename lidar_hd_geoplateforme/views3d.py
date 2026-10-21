"""Panneau « Vues 3D LiDAR » : jusqu'à 5 vues 3D d'un même COPC, chacune avec sa couche, ses couleurs et sa caméra."""
import csv
import os
import shutil
import subprocess
import tempfile

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, QThread, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                                 QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                                 QTabWidget, QVBoxLayout, QWidget)
from qgis.core import (Qgis, QgsColorRampShader, QgsMapLayerProxyModel, QgsPointCloudCategory, QgsPointCloudClassifiedRenderer,
                       QgsPointCloudLayer, QgsProject, QgsStyle, QgsMessageLog)
from qgis.gui import QgsMapLayerComboBox
import qgis._3d as q3

from .proxy_env import build_pdal_environment
from .views3d_logic import (GRAY, MAX_VIEWS, QUALITY, OPERATORS, ViewSettings, class_percentages, follow_pose, histogram,
                            poses_close, valid_range)

TAG = 'Vues 3D LiDAR'
CLONE_PROPERTY = 'lidarhd_3d_view_clone'
SCENE_NAMES = {i: f'Vue {i}' for i in range(1, MAX_VIEWS + 1)}


class SampleThread(QThread):
    """Échantillonne le COPC avec `pdal translate` + filters.decimation (une fois par dalle, en tâche de fond)."""
    done = pyqtSignal(object, str)

    def __init__(self, path, point_count, pdal, env, parent=None):
        super().__init__(parent)
        self.path, self.point_count, self.pdal, self.env = path, point_count, pdal, env

    def run(self):
        pdal, env = self.pdal, self.env  # environnement construit dans le thread principal (API QGIS non thread-safe)
        step = max(1, int(self.point_count // 800000))
        folder = tempfile.mkdtemp(prefix='lidarhd_histo_')
        out = os.path.join(folder, 'sample.csv')
        try:
            command = [pdal, 'translate', self.path, out, '--filters.decimation.step=%d' % step, '-f', 'filters.decimation',
                       '--writers.text.format=csv', '--writers.text.keep_unspecified=false']
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=900)
            if result.returncode != 0 or not os.path.exists(out):
                self.done.emit(None, (result.stderr or result.stdout)[-300:])
                return
            columns = {}
            with open(out, newline='', encoding='utf-8', errors='replace') as stream:
                reader = csv.reader(stream)
                names = next(reader)
                data = [[] for _ in names]
                for row in reader:
                    for k, value in enumerate(row):
                        data[k].append(float(value))
            columns = dict(zip(names, data))
            self.done.emit({'columns': columns, 'step': step}, '')
        except Exception as error:  # noqa: BLE001 - remonté à l'utilisateur
            self.done.emit(None, str(error))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class HistoWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(110)
        self.edges, self.counts, self.display, self.saturation = [], [], None, None
        self.color = QColor(70, 130, 180)

    def set_data(self, edges, counts, display=None, saturation=None):
        self.edges, self.counts, self.display, self.saturation = edges, counts, display, saturation
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(250, 250, 250))
        if not self.counts:
            painter.drawText(self.rect(), Qt.AlignCenter, 'Histogramme non calculé')
            return
        width, height, top = self.width(), self.height(), max(self.counts) or 1
        bar = width / len(self.counts)
        for k, count in enumerate(self.counts):
            h = height * count / top
            painter.fillRect(int(k * bar), int(height - h), max(1, int(bar)), int(h), self.color)
        low, high = self.edges[0], self.edges[-1]
        for rng, color in ((self.display, QColor(200, 0, 0)), (self.saturation, QColor(0, 150, 0))):
            if rng:
                painter.setPen(color)
                for value in rng:
                    x = int(width * (value - low) / (high - low or 1))
                    painter.drawLine(x, 0, x, height)


class ViewsPanel(QDockWidget):
    def __init__(self, iface):
        super().__init__(TAG, iface.mainWindow())
        self.setObjectName('LidarHd3DViewsPanel')
        self.iface = iface
        self.settings = {i: ViewSettings(index=i) for i in range(1, MAX_VIEWS + 1)}
        self.canvases, self.layers = {}, {}
        self.sample, self.sampler, self._loading = None, None, False
        self._syncing = False
        self._pending = {}
        self.windows = {}
        for stale in [l for l in QgsProject.instance().mapLayers().values() if l.customProperty(CLONE_PROPERTY)]:
            QgsProject.instance().removeMapLayer(stale.id())  # clones orphelins d'une session précédente
        self._build()
        QgsProject.instance().layerWasAdded.connect(self._layer_added)

    # ------------------------------------------------------------------ interface
    def _build(self):
        tabs = QTabWidget()
        self.tabs = tabs
        self.setWidget(tabs)
        # --- onglet Vues
        views = QWidget()
        form = QFormLayout(views)
        self.cloud = QgsMapLayerComboBox()
        self.cloud.setFilters(QgsMapLayerProxyModel.PointCloudLayer)
        self.cloud.layerChanged.connect(self._cloud_changed)
        fetch = QPushButton('Récupérer une dalle COPC (emprise de la carte)…')
        fetch.setToolTip('Ouvre le traitement « Extraire un COPC par édition » avec l’emprise courante de la carte 2D ; '
                         'le COPC produit est chargé dans le projet puis proposé dans la liste Nuage.')
        fetch.clicked.connect(self.fetch_copc)
        form.addRow(fetch)
        form.addRow('Nuage', self.cloud)
        self.count = QSpinBox()
        self.count.setRange(1, MAX_VIEWS)
        self.count.setValue(2)
        form.addRow('Nombre de vues', self.count)
        open_all = QPushButton('Ouvrir les vues')
        open_all.clicked.connect(self.open_views)
        form.addRow(open_all)
        self.view = QComboBox()
        self.view.addItems([SCENE_NAMES[i] for i in range(1, MAX_VIEWS + 1)])
        self.view.currentIndexChanged.connect(self._view_changed)
        form.addRow('Vue', self.view)
        row = QHBoxLayout()
        for text, slot in (('Ouvrir', self.open_current), ('Fermer', self.close_current), ('Recentrer', self.recenter)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        form.addRow(row)
        self.size = QDoubleSpinBox(); self.size.setRange(0.5, 30); self.size.setSingleStep(0.5)
        self.quality = QComboBox(); self.quality.addItems(list(QUALITY))
        self.edl = QCheckBox('Relief (EDL)')
        self.edl_strength = QDoubleSpinBox(); self.edl_strength.setRange(0, 5000); self.edl_strength.setDecimals(0)
        self.edl_distance = QSpinBox(); self.edl_distance.setRange(0, 50)
        self.show_cloud = QCheckBox('Nuage')
        self.triangles = QCheckBox('Rendu : surface (triangles)')
        for label, widget in (('Taille des points (px)', self.size), ('Qualité', self.quality), ('', self.edl),
                              ('Force EDL', self.edl_strength), ('Distance EDL', self.edl_distance),
                              ('Afficher', self.show_cloud), ('', self.triangles)):
            form.addRow(label, widget)
        for signal in (self.size.valueChanged, self.quality.currentIndexChanged, self.edl.toggled, self.edl_strength.valueChanged,
                       self.edl_distance.valueChanged, self.show_cloud.toggled, self.triangles.toggled):
            signal.connect(self._edited)
        # filtre
        self.f_attr = QComboBox(); self.f_op = QComboBox(); self.f_op.addItems(list(OPERATORS))
        self.f_v1 = QDoubleSpinBox(); self.f_v2 = QDoubleSpinBox()
        for box in (self.f_v1, self.f_v2):
            box.setRange(-1e9, 1e9); box.setDecimals(3)
        frow = QHBoxLayout()
        for w in (self.f_attr, self.f_op, self.f_v1, self.f_v2):
            frow.addWidget(w)
        form.addRow('Filtre de points', frow)
        brow = QHBoxLayout()
        for text, slot in (('Filtrer', self._apply_filter), ('Aucun filtre', self._clear_filter)):
            b = QPushButton(text); b.clicked.connect(slot); brow.addWidget(b)
        form.addRow(brow)
        # valeurs visibles
        self.v_attr = QComboBox(); self.v_attr.currentTextChanged.connect(self._visible_attr_changed)
        form.addRow('Valeurs visibles : attribut', self.v_attr)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Visible', 'Valeur', '%'])
        self.table.itemChanged.connect(self._visibility_edited)
        form.addRow(self.table)
        vrow = QHBoxLayout()
        for text, slot in (('Classer', self.classify), ('+', self._add_value), ('-', self._remove_values), ('Supprimer tout', self._clear_values)):
            b = QPushButton(text); b.clicked.connect(slot); vrow.addWidget(b)
        form.addRow(vrow)
        tabs.addTab(views, 'Vues')
        # --- onglet Synchro
        sync = QWidget(); sform = QVBoxLayout(sync)
        self.sync_list = QListWidget()
        for i in range(1, MAX_VIEWS + 1):
            item = QListWidgetItem(SCENE_NAMES[i]); item.setFlags(item.flags() | Qt.ItemIsUserCheckable); item.setCheckState(Qt.Unchecked)
            self.sync_list.addItem(item)
        self.sync_on = QCheckBox('Synchronisation active')
        self.sync_mode = QComboBox(); self.sync_mode.addItems(['Complet', 'Position seule'])
        for w in (QLabel('Vues à synchroniser'), self.sync_list, self.sync_on, self.sync_mode):
            sform.addWidget(w)
        sform.addStretch()
        tabs.addTab(sync, 'Synchro')
        # --- onglet Histo
        histo = QWidget(); hform = QFormLayout(histo)
        self.h_field = QComboBox(); self.h_field.currentTextChanged.connect(self._field_changed)
        hform.addRow('Champ', self.h_field)
        self.h_all = QCheckBox('Tout'); self.h_all.setChecked(True)
        self.h_min = QDoubleSpinBox(); self.h_max = QDoubleSpinBox()
        self.s_auto = QCheckBox('Automatique'); self.s_auto.setChecked(True)
        self.s_min = QDoubleSpinBox(); self.s_max = QDoubleSpinBox()
        for box in (self.h_min, self.h_max, self.s_min, self.s_max):
            box.setRange(-1e9, 1e9); box.setDecimals(3)
        for label, widgets in (('Plage affichée', (self.h_all, self.h_min, self.h_max)), ('Saturation', (self.s_auto, self.s_min, self.s_max))):
            r = QHBoxLayout()
            for w in widgets:
                r.addWidget(w)
            hform.addRow(label, r)
        for signal in (self.h_all.toggled, self.h_min.editingFinished, self.h_max.editingFinished, self.s_auto.toggled,
                       self.s_min.editingFinished, self.s_max.editingFinished):
            signal.connect(self._ranges_edited)
        self.histo = HistoWidget()
        hform.addRow(self.histo)
        self.status = QLabel('')
        hform.addRow(self.status)
        tabs.addTab(histo, 'Histo')
        tabs.currentChanged.connect(lambda index: self._refresh_histo() if tabs.tabText(index) == 'Histo' else None)
        self._cloud_changed(self.cloud.currentLayer())
        self._view_changed()

    # ------------------------------------------------------------------ état courant
    def current(self):
        return self.view.currentIndex() + 1

    def _source(self):
        return self.cloud.currentLayer()

    def _cloud_changed(self, layer):
        names = [a.name() for a in layer.attributes().attributes()] if layer else []
        for combo in (self.f_attr, self.v_attr, self.h_field):
            combo.blockSignals(True); combo.clear(); combo.addItems(names); combo.blockSignals(False)
        self.sample = None
        self.histo.set_data([], [])
        self._view_changed()

    def _view_changed(self, *_):
        s = self.settings[self.current()]
        self._loading = True
        self.size.setValue(s.point_size); self.quality.setCurrentText(s.quality); self.edl.setChecked(s.edl)
        self.edl_strength.setValue(s.edl_strength); self.edl_distance.setValue(s.edl_distance)
        self.show_cloud.setChecked(s.show_cloud); self.triangles.setChecked(s.triangles)
        if s.filter_attribute:
            self.f_attr.setCurrentText(s.filter_attribute)
        self.v_attr.setCurrentText(s.visible_attribute); self.h_field.setCurrentText(s.attribute)
        self._fill_table(s)
        self.h_all.setChecked(s.display_range is None); self.s_auto.setChecked(s.saturation is None)
        for box, rng, k in ((self.h_min, s.display_range, 0), (self.h_max, s.display_range, 1), (self.s_min, s.saturation, 0), (self.s_max, s.saturation, 1)):
            box.setValue(rng[k] if rng else 0)
        self._loading = False
        self._refresh_histo()

    def _edited(self, *_):
        if self._loading:
            return
        s = self.settings[self.current()]
        s.point_size, s.quality, s.edl = self.size.value(), self.quality.currentText(), self.edl.isChecked()
        s.edl_strength, s.edl_distance = self.edl_strength.value(), self.edl_distance.value()
        s.show_cloud, s.triangles = self.show_cloud.isChecked(), self.triangles.isChecked()
        self.apply(self.current())

    # ------------------------------------------------------------------ ouverture / fermeture
    def open_views(self):
        for i in range(1, self.count.value() + 1):
            self.open_view(i)

    def open_current(self):
        self.open_view(self.current())
        window = self.windows.get(self.current())
        if window is not None and not sip.isdeleted(window):
            window.show(); window.raise_()

    def open_view(self, i):
        source = self._source()
        if source is None or not source.isValid():
            self.iface.messageBar().pushWarning(TAG, 'Choisir un nuage de points COPC valide.')
            return
        self._purge_dead()
        if i in self.canvases:
            return
        if source.customProperty(CLONE_PROPERTY):
            return
        layer = source.clone()
        layer.setCustomProperty(CLONE_PROPERTY, '1')
        layer.setName(f'{source.name()} — {SCENE_NAMES[i]}')
        QgsProject.instance().addMapLayer(layer, False)
        before = set(QApplication.topLevelWidgets())
        canvas = self.iface.createNewMapCanvas3D(SCENE_NAMES[i])
        if canvas is None:
            QgsMessageLog.logMessage('createNewMapCanvas3D a échoué', TAG, Qgis.Warning)
            return
        self.layers[i], self.canvases[i] = layer, canvas
        self._show_window(i, [w for w in QApplication.topLevelWidgets() if w not in before and isinstance(w, QDialog)], source.name())
        self._hide_clones_from_combo()
        settings = canvas.mapSettings()
        settings.setCrs(layer.crs())
        settings.setExtent(layer.extent())
        self.apply(i)
        canvas.cameraController().cameraChanged.connect(lambda i=i: self._camera_changed(i))
        self._recenter(i)

    def close_current(self):
        i = self.current()
        if i in self.canvases:
            self._drop_view(i)

    def _show_window(self, i, dialogs, name):
        """QGIS nomme la fenêtre « Carte 3D N » et la crée flottante : titre explicite, taille, position en cascade, premier plan."""
        if not dialogs:
            return
        window = next((w for w in dialogs if w.metaObject().className() == 'QDialog' and (w.windowTitle().startswith('Carte 3D') or w.windowTitle() == SCENE_NAMES[i])), None)  # exclut la boîte de mesure 3D
        if window is None:
            return
        window.setWindowTitle(f'{SCENE_NAMES[i]} — {name}')
        window.resize(720, 600)
        geometry = self.iface.mainWindow().frameGeometry()
        window.move(geometry.left() + 80 + 40 * (i - 1), geometry.top() + 120 + 40 * (i - 1))
        window.show()
        window.raise_()
        window.activateWindow()
        self.windows[i] = window

    def fetch_copc(self):
        """Lance l'algorithme d'extraction (interface Processing complète) avec l'emprise de la carte 2D."""
        import processing
        canvas = self.iface.mapCanvas()
        extent, crs = canvas.extent(), canvas.mapSettings().destinationCrs()
        text = f'{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()} [{crs.authid()}]'
        processing.execAlgorithmDialog('lidarhd_geoplateforme:extract_editions',
                                       {'EXTENT': text, 'EDITION_MODE': 1, 'RESOLUTION': 0.5, 'LOAD': True})

    def _layer_added(self, layer):
        """Un nuage de points qui vient d'être chargé (ex. COPC extrait) devient le nuage proposé."""
        if isinstance(layer, QgsPointCloudLayer) and not layer.customProperty(CLONE_PROPERTY):
            QTimer.singleShot(500, lambda: self.cloud.setLayer(layer) if not (sip.isdeleted(self.cloud) or sip.isdeleted(layer)) else None)

    def _hide_clones_from_combo(self):
        self.cloud.setExceptedLayerList([l for l in QgsProject.instance().mapLayers().values() if l.customProperty(CLONE_PROPERTY)])

    def _purge_dead(self):
        """Vues dont la fenêtre 3D a été détruite (fermée par sa croix) : on libère leur clone, elles pourront être rouvertes."""
        for i in [i for i, c in self.canvases.items() if sip.isdeleted(c)]:
            layer = self.layers.pop(i, None)
            del self.canvases[i]
            self._pending.pop(i, None)
            if layer is not None and not sip.isdeleted(layer):
                layer_id = layer.id()
                QTimer.singleShot(4000, lambda layer_id=layer_id: QgsProject.instance().removeMapLayer(layer_id))

    def _drop_view(self, i):
        if sip.isdeleted(self.canvases[i]):
            self._purge_dead()
            return
        """Ferme la vue puis retire la couche clonée APRÈS la destruction asynchrone de la scène 3D (sinon plantage QGIS)."""
        layer_id = self.layers[i].id()
        self._pending.pop(i, None)
        window = self.windows.pop(i, None)
        self.iface.closeMapCanvas3D(SCENE_NAMES[i])
        if window is not None and not sip.isdeleted(window):
            window.close()
        del self.canvases[i], self.layers[i]
        QTimer.singleShot(4000, lambda: QgsProject.instance().removeMapLayer(layer_id))

    def close_all(self):
        for i in list(self.canvases):
            self._drop_view(i)

    def recenter(self):
        self._recenter(self.current())

    def _recenter(self, i):
        if i not in self.canvases:
            return
        extent = self.layers[i].extent()
        distance = max(extent.width(), extent.height(), 10.0) * 1.5
        self.canvases[i].cameraController().resetView(distance)

    # ------------------------------------------------------------------ rendu d'une vue
    def _ramp(self):
        ramp = QgsStyle.defaultStyle().colorRamp('Turbo') or QgsStyle.defaultStyle().colorRamp('Viridis')
        return ramp

    def _bounds(self, attribute):
        stats = self._source().statistics()
        lo, hi = stats.minimum(attribute), stats.maximum(attribute)
        if self.sample and attribute in self.sample['columns']:
            values = self.sample['columns'][attribute]
            lo, hi = min(values), max(values)
        if lo != lo or hi != hi or lo >= hi:  # NaN ou plage vide
            lo, hi = 0.0, 1.0
        return lo, hi

    def _symbol(self, s):
        if s.attribute == 'Classification':
            symbol = q3.QgsClassificationPointCloud3DSymbol()
            symbol.setAttribute('Classification')
            categories = []
            for cat in QgsPointCloudClassifiedRenderer.defaultCategories():
                inside = s.display_range is None or s.display_range[0] <= cat.value() <= s.display_range[1]
                categories.append(QgsPointCloudCategory(cat.value(), cat.color() if inside else QColor(*GRAY), cat.label(), cat.renderState()))
            symbol.setCategoriesList(categories)
        else:
            symbol = q3.QgsColorRampPointCloud3DSymbol()
            symbol.setAttribute(s.attribute)
            lo, hi = s.saturation if s.saturation else self._bounds(s.attribute)
            shader = QgsColorRampShader(lo, hi, self._ramp())
            shader.classifyColorRamp(5)
            symbol.setColorRampShader(shader)
            symbol.setColorRampShaderMinMax(lo, hi)
        symbol.setPointSize(s.point_size)
        symbol.setRenderAsTriangles(s.triangles)
        return symbol

    def apply(self, i):
        """Regroupe les modifications rapprochées (évite de remplacer le rendu 3D pendant le chargement des nœuds)."""
        if i not in self.canvases:
            return
        if i not in self._pending:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda i=i: self._apply_now(i))
            self._pending[i] = timer
        self._pending[i].start(200)

    def _apply_now(self, i):
        self._pending.pop(i, None)
        if i not in self.canvases:
            return
        if sip.isdeleted(self.canvases[i]) or sip.isdeleted(self.layers[i]):  # fenêtre fermée par sa croix
            self.canvases.pop(i, None)
            self.layers.pop(i, None)
            return
        s, layer, canvas = self.settings[i], self.layers[i], self.canvases[i]
        layer.setSubsetString(s.subset_string())
        renderer = q3.QgsPointCloudLayer3DRenderer()
        renderer.setLayer(layer)
        renderer.setSymbol(self._symbol(s))
        renderer.setPointRenderingBudget(s.budget())
        layer.setRenderer3D(renderer)
        settings = canvas.mapSettings()
        wanted = [layer] if s.show_cloud else []
        if settings.layers() != wanted:
            settings.setLayers(wanted)
        settings.setEyeDomeLightingEnabled(s.edl)
        settings.setEyeDomeLightingStrength(s.edl_strength)
        settings.setEyeDomeLightingDistance(int(round(s.edl_distance)))
        layer.triggerRepaint()

    # ------------------------------------------------------------------ filtre et valeurs visibles
    def _apply_filter(self):
        s = self.settings[self.current()]
        s.filter_attribute, s.filter_operator = self.f_attr.currentText(), self.f_op.currentText()
        s.filter_value, s.filter_value2 = self.f_v1.value(), self.f_v2.value()
        self.apply(self.current())

    def _clear_filter(self):
        self.settings[self.current()].clear_filter()
        self.apply(self.current())

    def _fill_table(self, s):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        for value, percent in self._known_values(s):
            self._add_row(s, value, percent)

    def _known_values(self, s):
        return getattr(self, '_table_values', {}).get((s.index, s.visible_attribute), [])

    def _add_row(self, s, value, percent=None):
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        check = QTableWidgetItem(); check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check.setCheckState(Qt.Unchecked if value in s.hidden_values else Qt.Checked)
        self.table.setItem(row, 0, check)
        self.table.setItem(row, 1, QTableWidgetItem(('%g' % value)))
        self.table.setItem(row, 2, QTableWidgetItem('' if percent is None else '%.1f' % percent))
        self.table.blockSignals(False)

    def _remember_table(self, s):
        values = getattr(self, '_table_values', {})
        rows = []
        for row in range(self.table.rowCount()):
            pct = self.table.item(row, 2).text()
            rows.append((float(self.table.item(row, 1).text()), float(pct) if pct else None))
        values[(s.index, s.visible_attribute)] = rows
        self._table_values = values

    def _visibility_edited(self, item):
        if self._loading or item.column() != 0:
            return
        s = self.settings[self.current()]
        value = float(self.table.item(item.row(), 1).text())
        (s.hidden_values.discard if item.checkState() == Qt.Checked else s.hidden_values.add)(value)
        self.apply(self.current())

    def _visible_attr_changed(self, name):
        if self._loading or not name:
            return
        s = self.settings[self.current()]
        s.visible_attribute, s.hidden_values = name, set()
        self._fill_table(s)
        self.apply(self.current())

    def _add_value(self):
        s = self.settings[self.current()]
        self._add_row(s, 0.0)
        self._remember_table(s)

    def _remove_values(self):
        s = self.settings[self.current()]
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            s.hidden_values.discard(float(self.table.item(row, 1).text()))
            self.table.removeRow(row)
        self._remember_table(s)
        self.apply(self.current())

    def _clear_values(self):
        s = self.settings[self.current()]
        s.hidden_values = set()
        self.table.setRowCount(0)
        self._remember_table(s)
        self.apply(self.current())

    def classify(self):
        s = self.settings[self.current()]
        self._with_sample(lambda: self._classify_now(s))

    def _classify_now(self, s):
        column = self.sample['columns'].get(s.visible_attribute) if self.sample else None
        if not column:
            return
        counts = {}
        for value in column:
            counts[value] = counts.get(value, 0) + 1
        if len(counts) > 300:
            self.status.setText('Attribut à valeurs continues : ajouter les valeurs avec +.')
            return
        self.table.setRowCount(0)
        for value, percent in class_percentages(counts).items():
            self._add_row(s, value, percent)
        self._remember_table(s)

    # ------------------------------------------------------------------ histogramme
    def _with_sample(self, then):
        if self.sample:
            then()
            return
        source = self._source()
        if source is None or self.sampler is not None:
            return
        path = source.source().split('|')[0]
        if not os.path.isfile(path):
            self.status.setText('Histogramme disponible pour un fichier COPC, LAS ou LAZ local seulement.')
            return
        self.status.setText('Calcul de l’échantillon en tâche de fond…')
        pdal = shutil.which('pdal')
        if not pdal:
            self.status.setText('pdal introuvable.')
            return
        env, _ = build_pdal_environment(pdal)
        self.sampler = SampleThread(path, source.pointCount(), pdal, env, self)

        def finished(data, error):
            self.sampler = None
            if data is None:
                self.status.setText('Échantillon impossible : ' + error)
                return
            self.sample = data
            self.status.setText('Échantillon : 1 point sur %d.' % data['step'])
            then()
        self.sampler.done.connect(finished)
        self.sampler.start()

    def _field_changed(self, name):
        if self._loading or not name:
            return
        s = self.settings[self.current()]
        s.set_color_attribute(name)
        self._view_changed()
        self.apply(self.current())

    def _ranges_edited(self, *_):
        if self._loading:
            return
        s = self.settings[self.current()]
        s.display_range = None if self.h_all.isChecked() else ((self.h_min.value(), self.h_max.value()) if valid_range(self.h_min.value(), self.h_max.value()) else None)
        s.saturation = None if self.s_auto.isChecked() else ((self.s_min.value(), self.s_max.value()) if valid_range(self.s_min.value(), self.s_max.value()) else None)
        if not self.h_all.isChecked() and s.display_range is None:
            self.status.setText('Le minimum doit être inférieur au maximum.')
        self.apply(self.current())
        self._refresh_histo()

    def _refresh_histo(self):
        s = self.settings[self.current()]

        def draw():
            column = self.sample['columns'].get(s.attribute)
            if not column:
                self.histo.set_data([], [])
                return
            edges, counts = histogram(column, 64)
            self.histo.set_data(edges, counts, s.display_range, s.saturation)
        if self.sample:
            draw()
        elif self._source() is not None and self.tabs.tabText(self.tabs.currentIndex()) == 'Histo':
            self._with_sample(draw)

    # ------------------------------------------------------------------ synchronisation des caméras
    def _synced(self):
        return [i + 1 for i in range(MAX_VIEWS) if self.sync_list.item(i).checkState() == Qt.Checked and (i + 1) in self.canvases]

    @staticmethod
    def _pose_dict(pose):
        c = pose.centerPoint()
        return dict(x=c.x(), y=c.y(), z=c.z(), distance=pose.distanceFromCenterPoint(), pitch=pose.pitchAngle(), heading=pose.headingAngle())

    def _camera_changed(self, i):
        if self._syncing or not self.sync_on.isChecked() or i not in self._synced():
            return
        source = self._pose_dict(self.canvases[i].cameraController().cameraPose())
        self._syncing = True
        try:
            for j in self._synced():
                if j == i:
                    continue
                controller = self.canvases[j].cameraController()
                pose = controller.cameraPose()
                new = follow_pose(source, self._pose_dict(pose), self.sync_mode.currentText())
                if poses_close(new, self._pose_dict(pose)):
                    continue
                from qgis.core import QgsVector3D
                pose.setCenterPoint(QgsVector3D(new['x'], new['y'], new['z']))
                pose.setDistanceFromCenterPoint(new['distance'])
                pose.setPitchAngle(new['pitch'])
                pose.setHeadingAngle(new['heading'])
                controller.setCameraPose(pose)
        finally:
            self._syncing = False
