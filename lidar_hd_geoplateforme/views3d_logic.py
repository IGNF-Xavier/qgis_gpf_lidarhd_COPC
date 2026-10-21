"""Logique pure (sans QGIS) du panneau « Vues 3D LiDAR » : réglages par vue, filtres, histogramme, synchronisation."""
from dataclasses import dataclass, field

MAX_VIEWS = 5
QUALITY = {'Fluide': 1_000_000, 'Équilibrée': 2_000_000, 'Fine': 5_000_000}
OPERATORS = {'=': '=', '≠': '<>', '<': '<', '≤': '<=', '>': '>', '≥': '>=', 'entre': 'between'}
GRAY = (160, 160, 160)


def _num(value):
    value = float(value)
    return str(int(value)) if value == int(value) else repr(value)


def filter_clause(attribute, operator, value, value2=None):
    """Clause d'expression pour QgsPointCloudLayer.setSubsetString ('' si aucun filtre)."""
    if not attribute or operator not in OPERATORS:
        return ''
    if OPERATORS[operator] == 'between':
        low, high = sorted((float(value), float(value2)))
        return f'({attribute} >= {_num(low)} AND {attribute} <= {_num(high)})'
    return f'{attribute} {OPERATORS[operator]} {_num(value)}'


def hidden_clause(attribute, hidden):
    """Exclut les valeurs masquées d'un attribut."""
    return ' AND '.join(f'{attribute} <> {_num(v)}' for v in sorted(hidden)) if hidden else ''


def combine(*clauses):
    return ' AND '.join(c for c in clauses if c)


def valid_range(low, high):
    return low is not None and high is not None and float(low) < float(high)


@dataclass
class ViewSettings:
    """Réglages propres à une vue (jamais partagés entre vues)."""
    index: int = 1
    point_size: float = 2.0
    quality: str = 'Équilibrée'
    edl: bool = True
    edl_strength: float = 1000.0
    edl_distance: int = 1
    show_cloud: bool = True
    triangles: bool = False
    attribute: str = 'Classification'      # attribut qui colore la vue
    display_range: tuple = None            # (min, max) ou None = tout
    saturation: tuple = None               # (min, max) ou None = automatique
    filter_attribute: str = ''
    filter_operator: str = '='
    filter_value: float = None
    filter_value2: float = None
    visible_attribute: str = 'Classification'
    hidden_values: set = field(default_factory=set)

    def budget(self):
        return QUALITY.get(self.quality, QUALITY['Équilibrée'])

    def set_color_attribute(self, attribute):
        """Changer le champ coloré remet plage et saturation en automatique et efface les valeurs masquées de l'ancien champ."""
        if attribute != self.attribute:
            self.attribute = attribute
            self.display_range = None
            self.saturation = None
            if self.visible_attribute != attribute:
                self.visible_attribute = attribute
                self.hidden_values = set()

    def subset_string(self):
        clause = ''
        if self.filter_attribute and self.filter_value is not None:
            clause = filter_clause(self.filter_attribute, self.filter_operator, self.filter_value, self.filter_value2)
        return combine(clause, hidden_clause(self.visible_attribute, self.hidden_values))

    def clear_filter(self):
        self.filter_attribute = ''
        self.filter_value = self.filter_value2 = None


def histogram(values, bins=64, vmin=None, vmax=None):
    """Histogramme simple : retourne (bornes, comptes)."""
    values = list(values)
    if not values:
        return [], []
    lo = min(values) if vmin is None else vmin
    hi = max(values) if vmax is None else vmax
    if hi <= lo:
        hi = lo + 1
    counts = [0] * bins
    scale = bins / (hi - lo)
    for v in values:
        if lo <= v <= hi:
            counts[min(bins - 1, int((v - lo) * scale))] += 1
    return [lo + (hi - lo) * i / bins for i in range(bins + 1)], counts


def class_percentages(counts):
    total = sum(counts.values()) or 1
    return {k: 100.0 * v / total for k, v in sorted(counts.items())}


def follow_pose(source, target, mode):
    """Pose caméra à appliquer à une vue suiveuse. Poses = dict(x, y, z, distance, pitch, heading).

    'Complet' : tout copié ; 'Position seule' : point et distance copiés, angles conservés."""
    if mode == 'Position seule':
        result = dict(target)
        for key in ('x', 'y', 'z', 'distance'):
            result[key] = source[key]
        return result
    return dict(source)


def poses_close(a, b, tol=1e-6):
    return all(abs(a[k] - b[k]) <= tol * max(1.0, abs(a[k])) for k in a)
