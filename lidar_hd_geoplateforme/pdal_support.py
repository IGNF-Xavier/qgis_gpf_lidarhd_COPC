"""Logique pure (sans QGIS) : stratégies d'URL, environnement réseau PDAL, pipeline, diagnostic des journaux.

Ce module est volontairement indépendant de QGIS afin d'être testable en Python seul.
"""
import os

CA_ENV_KEYS = ('ARBITER_CA_INFO', 'SSL_CERT_FILE', 'CURL_CA_BUNDLE')


def chunk_url(url):
    """Ajoute le contexte « chunk » recommandé par le tutoriel (idempotent)."""
    return url if '/chunk/' in url else url.replace('/telechargement/', '/chunk/telechargement/')


def url_sets(urls, mode):
    """Stratégies d'URL dans l'ordre d'essai.

    mode 0 : automatique = chunk en priorité, URL WFS originale en repli
    mode 1 : URL WFS originale uniquement
    mode 2 : URL chunk uniquement
    """
    original = list(urls)
    chunk = [chunk_url(u) for u in original]
    if mode == 1:
        return [('URL WFS originale', original)]
    if mode == 2:
        return [('URL chunk', chunk)]
    if chunk == original:
        return [('URL chunk', chunk)]
    return [('URL chunk', chunk), ('URL WFS originale', original)]


def attempt_plan(selected_urls, strategies):
    """Liste des tentatives de pipeline : URLs validées par le précontrôle, puis chaque repli distinct."""
    plan = [('URLs retenues par le précontrôle Range', list(selected_urls))]
    seen = [list(selected_urls)]
    for label, urls in strategies:
        if urls not in seen:
            plan.append(('Repli : ' + label, list(urls)))
            seen.append(list(urls))
    return plan


def find_ca_bundle(environ, pdal_path=None, exists=os.path.isfile):
    """Bundle de certificats utilisable par le curl/OpenSSL de PDAL (arbiter).

    PDAL sous Windows/QGIS n'utilise pas le magasin de certificats Windows : sans bundle explicite,
    OpenSSL répond « no trust anchors configured » et chaque lecture HTTPS échoue (avec nouvelles tentatives lentes).
    """
    for key in CA_ENV_KEYS:
        value = environ.get(key)
        if value and exists(value):
            return value, key
    if pdal_path:
        root = os.path.dirname(os.path.abspath(pdal_path))
        for candidate in (os.path.join(root, 'curl-ca-bundle.crt'),
                          os.path.join(root, '..', 'apps', 'openssl', 'certs', 'cert.pem'),
                          os.path.join(root, '..', 'etc', 'ssl', 'cert.pem'),
                          os.path.join(root, '..', 'ssl', 'cert.pem'),
                          os.path.join(root, '..', 'Library', 'ssl', 'cacert.pem')):
            candidate = os.path.normpath(candidate)
            if exists(candidate):
                return candidate, 'à côté de pdal'
    return None, None


def apply_network_environment(env, proxy_url=None, no_proxy=None, ca_bundle=None):
    """Complète l'environnement du subprocess PDAL. Retourne la liste des variables positionnées (noms seulement)."""
    set_keys = []
    if proxy_url:
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            env[key] = proxy_url
            set_keys.append(key)
    if no_proxy:
        for key in ('NO_PROXY', 'no_proxy'):
            env[key] = no_proxy
            set_keys.append(key)
    if ca_bundle:
        # ARBITER_CA_INFO est la variable réellement lue par PDAL ; les autres servent à cURL/GDAL.
        for key in CA_ENV_KEYS:
            env[key] = ca_bundle
            set_keys.append(key)
    return set_keys


def classify_pdal_log(text):
    """Explications lisibles déduites d'un journal PDAL/cURL (verbeux ou non)."""
    hints = []
    low = (text or '').lower()
    if 'no trust anchors' in low or 'ssl peer certificate' in low or ('certificate' in low and 'verify' in low):
        hints.append("Échec TLS : PDAL ne trouve pas de certificats de confiance (bundle CA). "
                     "Définir ARBITER_CA_INFO vers un bundle PEM (ex. curl-ca-bundle.crt de QGIS).")
    if "couldn't connect" in low or 'could not connect' in low or 'connection timed out' in low or 'timeout was reached' in low:
        hints.append("Connexion impossible depuis PDAL : proxy/pare-feu (QGIS passe peut-être par un proxy PAC que PDAL ne connaît pas).")
    if 'proxy' in low and ('407' in low or 'authentication' in low):
        hints.append("Le proxy exige une authentification que PDAL n'a pas reçue.")
    if 'could not read from' in low:
        hints.append("PDAL signale « Could not read from » : lecture HTTP distante en échec après nouvelles tentatives.")
    return hints


def key_network_lines(text, limit=12):
    """Extrait les lignes utiles d'un journal ARBITER_VERBOSE (proxy, TLS, échec cURL)."""
    keys = ('proxy:', 'curl failure', 'trust anchors', 'verify result', 'http/1.1 4', 'http/1.1 5',
            'could not read', 'establish http proxy tunnel', 'connect tunnel')
    lines = [line.strip() for line in (text or '').splitlines() if any(k in line.lower() for k in keys)]
    seen = []
    for line in lines:
        if line not in seen:
            seen.append(line)
    return seen[:limit]


def bounds_string(xmin, xmax, ymin, ymax):
    return f'([{xmin},{xmax}],[{ymin},{ymax}])'


def pipeline_stages(readers, output, resolution=0):
    """Pipeline conforme au tutoriel : un readers.copc par dalle, puis fusion explicite, puis writers.copc local.

    `filters.merge` est nécessaire : sans lui, PDAL 2.10 n'a écrit qu'une partie des points lorsque
    plusieurs readers.copc alimentent directement le writer (75 085 points au lieu de 160 659 mesurés).
    """
    output = os.path.abspath(output)
    stages = []
    for filename, bounds in readers:
        stage = {'type': 'readers.copc', 'filename': filename, 'bounds': bounds}
        if resolution and resolution > 0:
            stage['resolution'] = resolution
        stages.append(stage)
    if len(stages) > 1:
        stages.append({'type': 'filters.merge'})
    stages.append({'type': 'writers.copc', 'filename': output, 'forward': 'all'})
    return stages


def progress_message(elapsed, exists, size_bytes, previous_size, idle_seconds):
    """Message de suivi : l'absence de fichier n'est jamais présentée comme un blocage."""
    head = f'PDAL actif : {int(elapsed)} s'
    if not exists:
        return head + ' — fichier de sortie non encore créé (ouverture/lecture distante en cours)'
    delta = max(0, size_bytes - max(previous_size, 0))
    return (head + f' — COPC local : {size_bytes / 1048576:.1f} Mio — croissance depuis le dernier contrôle : '
            f'{delta / 1048576:.1f} Mio (sans croissance : {int(idle_seconds)} s)')
