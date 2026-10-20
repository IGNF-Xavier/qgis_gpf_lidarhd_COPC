"""Construit l'environnement réseau du subprocess PDAL à partir de la configuration réseau effective de QGIS.

QGIS résout le proxy URL par URL (proxy configuré, fichier PAC/WPAD du système) alors que PDAL (cURL) ne lit
que les variables d'environnement : sans cette passerelle, PDAL tente une connexion directe (bloquée) ou échoue en TLS.
"""
import os
import urllib.parse
from qgis.PyQt.QtCore import QSettings, QUrl
from qgis.PyQt.QtNetwork import QNetworkProxy, QNetworkProxyFactory, QNetworkProxyQuery
from qgis.core import QgsNetworkAccessManager
from .pdal_support import apply_network_environment, find_ca_bundle

SAMPLE_URL = 'https://data.geopf.fr/chunk/telechargement/'


def _bool(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _proxy_url(host, port, user='', password=''):
    auth = ''
    if user:
        auth = urllib.parse.quote(str(user), safe='')
        if password:
            auth += ':' + urllib.parse.quote(str(password), safe='')
        auth += '@'
    return 'http://' + auth + str(host) + (':' + str(port) if port else '')


def _usable(proxy):
    no_proxy = getattr(QNetworkProxy, 'NoProxy', 2)
    return bool(proxy) and proxy.type() != no_proxy and bool(proxy.hostName())


def _resolve_proxy(sample_url):
    """Retourne (proxy, source) pour l'URL, dans l'ordre : proxy QGIS, réglages QGIS, résolution système/PAC."""
    manager = QgsNetworkAccessManager.instance()
    if _usable(manager.proxy()):
        return manager.proxy(), 'proxy actif de QgsNetworkAccessManager'
    settings = QSettings()
    host = settings.value('proxy/proxyHost', '')
    if _bool(settings.value('proxy/proxyEnabled', False)) and host:
        proxy = QNetworkProxy(QNetworkProxy.HttpProxy, str(host), int(settings.value('proxy/proxyPort', 0) or 0),
                              str(settings.value('proxy/proxyUser', '') or ''), str(settings.value('proxy/proxyPassword', '') or ''))
        return proxy, 'paramètres proxy QGIS'
    query = QNetworkProxyQuery(QUrl(sample_url))
    candidates = []
    for factory in manager.proxyFactories():
        candidates.extend(factory.queryProxy(query))
    # Résolution du système (PAC / WPAD / proxy Windows), la même que celle utilisée par Qt pour QGIS.
    candidates.extend(QNetworkProxyFactory.systemProxyForQuery(query))
    for proxy in candidates:
        if _usable(proxy):
            return proxy, 'proxy système/PAC résolu pour ' + urllib.parse.urlsplit(sample_url).hostname
    return None, None


def build_pdal_environment(pdal_path=None, sample_url=SAMPLE_URL):
    env = os.environ.copy()
    proxy, source = _resolve_proxy(sample_url)
    proxy_url = None
    if proxy is not None:
        proxy_url = _proxy_url(proxy.hostName(), proxy.port(), proxy.user(), proxy.password())
    else:
        source = 'environnement système' if any(env.get(k) for k in ('HTTPS_PROXY', 'https_proxy')) else 'aucun proxy (connexion directe)'
    excluded = []
    raw = QSettings().value('proxy/proxyExcludedUrls', [])
    if isinstance(raw, str):
        excluded = [item.strip() for item in raw.replace('|', ';').split(';') if item.strip()]
    elif raw:
        excluded = [str(item).strip() for item in raw if str(item).strip()]
    ca_bundle, ca_source = find_ca_bundle(env, pdal_path)
    apply_network_environment(env, proxy_url, ','.join(excluded) if excluded else None, ca_bundle)
    final_proxy = proxy_url or env.get('HTTPS_PROXY') or env.get('https_proxy')
    host = urllib.parse.urlsplit(final_proxy).hostname if final_proxy else None
    port = urllib.parse.urlsplit(final_proxy).port if final_proxy else None
    # Ne jamais exposer les identifiants dans le journal.
    summary = {'proxy_injected': bool(proxy_url), 'proxy_active': bool(final_proxy), 'source': source, 'host': host, 'port': port,
               'excluded_count': len(excluded), 'ca_bundle': ca_bundle, 'ca_source': ca_source}
    return env, summary
