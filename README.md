# LiDAR HD Géoplateforme — plugin QGIS

> ⚠️ **Plugin expérimental et non officiel.** Il n'est ni développé ni supporté par l'IGN. Les résultats doivent être
> vérifiés ; l'interface et le comportement peuvent changer sans préavis. Testé principalement sous Windows avec QGIS 3.40
> et PDAL 2.10 ; QGIS 4.x / Qt6 est visé mais n'a pas été validé.

Plugin **Processing** pour QGIS qui extrait une zone du **LiDAR HD** de la [Géoplateforme](https://geoplateforme.fr/)
et produit un **COPC local**, en lisant les COPC sources **à distance** (requêtes HTTP Range) sans les télécharger en entier.

## Référence : le tutoriel

La méthode suit le tutoriel de [esgn](https://gist.github.com/esgn)
[« Extraire une zone du LiDAR HD à distance avec PDAL et PDAL Wrench »](https://gist.github.com/esgn/4bbf298ad76f4d72e9f3c133cbc96cf1) :

- les dalles concernées sont trouvées par le WFS `IGNF_LIDAR-HD_METADONNEE:metadata` (champ `url_npl`) ;
- chaque dalle est lue par un `readers.copc` distinct, limité à l'emprise par `bounds` ;
- le contexte **`chunk`** est ajouté aux URLs (`https://data.geopf.fr/chunk/telechargement/…`), ce que recommande le tutoriel
  pour éviter les limites d'usage ;
- le résultat est écrit en local.

Le plugin automatise cette chaîne dans QGIS et ajoute la détection des éditions, la reprojection de l'emprise et le suivi.

## Fonctionnement

```
Emprise QGIS → WFS metadata → dalles nécessaires → URLs chunk (repli : URL WFS)
  → readers.copc distants (bounds + resolution) → filters.merge → writers.copc local
```

Deux algorithmes (boîte à outils Processing › *LiDAR HD Géoplateforme*) :

1. **Lister les éditions disponibles** : inventaire JSON des éditions (`date_edition`) sur une emprise.
2. **Extraire un COPC par édition** : toutes les éditions, la plus récente (couverture composite par dalle) ou une sélection.

Points d'attention :

- **Date catalogue ≠ date de ressource** : la date du catalogue peut différer de celle présente dans l'URL ; les deux sont journalisées.
- **SCR** : détecté depuis l'emprise, le paramètre de repli ou le projet ; l'emprise est reprojetée dans le SCR des données
  (`systeme_planimetrique`, ex. LAMB93 → EPSG:2154) avant d'être passée à `bounds`.
- **Résolution** : contrôle le niveau de détail de lecture COPC (0 = native ; 0,5 m = compromis ; 2 m et plus = aperçu), pas une taille de pixel.
- **`filters.merge` explicite** : nécessaire. Mesuré avec PDAL 2.10 sur deux dalles : 160 659 points avec, 75 085 sans.
- **Mode strict** : si une dalle nécessaire est illisible, le traitement s'arrête et aucun COPC incomplet n'est produit.
- **Stratégie d'URL** : *chunk* d'abord, URL WFS originale en repli (une seconde pipeline est reconstruite).

## Vues 3D LiDAR (0.6.0, expérimental)

Menu *Extensions › LiDAR HD Géoplateforme › Vues 3D LiDAR* : un panneau pour comparer 1 à 5 vues 3D d'une même dalle COPC,
chacune avec sa couche (clone, sans copie de données), ses couleurs et sa caméra. Prérequis : QGIS ≥ 3.40.

- **Vues** : taille des points, qualité (1 / 2 / 5 M de points), relief EDL, rendu en triangles, recentrage, filtre de points
  (attribut, opérateur, valeur), tableau des *valeurs visibles* (« Classer » donne les pourcentages).
- **Histo** : champ coloré, plage affichée (classes hors plage en gris pour la classification), saturation des rampes, histogramme.
- **Synchro** : caméras synchronisées, mode *Complet* ou *Position seule*.

> ⚠️ **Non validé visuellement.** Le panneau crée les vues et applique les réglages (testé par script), mais le rendu des points 3D n'a pas pu
> être vérifié : sur le poste de test (AMD Radeon intégré, pilote de 2022, QGIS 3.40.4 et 3.44.8) la scène 3D n'affiche que la carte 2D plaquée
> sur le terrain, jamais les points. Un pilote graphique récent est conseillé ; retours bienvenus.

Limites de cette version : histogramme et « Classer » calculés sur un échantillon (`pdal translate` + décimation, fichier local seulement) ;
réglage des plages par champs numériques (pas de poignées sur l'histogramme) ; pas encore de découpage, de MNT, d'outils par vue
ni de sauvegarde des vues dans le projet. Testé sur QGIS 3.40.4.

## Installation

Télécharger `lidar_hd_geoplateforme_<version>.zip` depuis les [Releases](https://github.com/IGNF-Xavier/qgis_gpf_lidarhd_COPC/releases),
puis QGIS › *Extensions* › *Installer depuis un ZIP* (cocher les extensions expérimentales si besoin).
Prérequis : QGIS ≥ 3.32 avec `pdal` accessible (inclus dans l'installeur QGIS OSGeo4W/MSI).

## Réseau d'entreprise : proxy PAC et certificats

PDAL s'exécute dans un processus séparé qui n'utilise pas la pile réseau de QGIS. Deux causes d'échec (« Could not read from »)
ont été identifiées et corrigées dans la 0.5.0 :

- **Certificats** : le curl de PDAL n'a pas de bundle CA (`no trust anchors configured`) → le plugin définit `ARBITER_CA_INFO`
  (bundle de QGIS, ou variable déjà présente) ;
- **Proxy** : QGIS suit le proxy résolu par le fichier PAC du système, PDAL non → le plugin résout le proxy effectif et le transmet
  (`HTTP(S)_PROXY`, `NO_PROXY`). Les identifiants ne sont jamais journalisés.

## Tests

```bash
python -I -m unittest discover -s lidar_hd_geoplateforme/tests -t lidar_hd_geoplateforme
```

Un test d'intégration réel (réseau + `pdal`) produit un COPC local à partir de deux dalles :

```bash
LIDARHD_LIVE=1 LIDARHD_PDAL=/chemin/vers/pdal python -I lidar_hd_geoplateforme/tests/test_integration_live.py
```

Les autres tests sont essentiellement statiques (contrat d'interface) ou sans QGIS.

## Licence

[GNU GPL v2 ou ultérieure](LICENSE), compatible avec la licence de QGIS. Les données LiDAR HD sont soumises à la licence de l'IGN
(Licence Ouverte Etalab 2.0) ; consulter la Géoplateforme.
