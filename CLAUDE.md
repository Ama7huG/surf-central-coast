# Central Coast Surf — contexte du projet

Projet perso d'Atamaï (étudiant en échange à UCSB, surfe surtout à Sands, Isla Vista).
Prévisions de surf pour 28 spots de Ventura à Cayucos. Réponses en français, site en anglais.

## Architecture

- `surf.py` : Python 3.9+, **bibliothèque standard uniquement** (pas de pip). Récupère toutes les sources en parallèle, note chaque spot heure par heure, écrit `web/data.js` (`window.SURF_DATA = {...}`).
- `config/spots.json` : les spots (position, région, priorité carte, fenêtre de marée, tailles, fenêtre de houle, fiche en anglais).
- `config/mop_points.csv` : liste des points CDIP, téléchargée au premier lancement depuis Zenodo (`CDIP_Transects.csv`, colonnes `ID, Lon_BackBeach, Lat_BackBeach, Lon_Pred, Lat_Pred, Pred_Depth, ShoreNormal, Flag`).
- `web/index.html` : page statique unique (HTML/CSS/JS), Leaflet via unpkg, fond satellite Esri World Imagery + étiquettes Dark Gray Reference (sans clé ; CARTO exige désormais une clé API). Houle animée en canvas (`swellLayer`) : masque eau/terre lu sur des tuiles Esri Ocean cachées (CORS ok), ombre de houle derrière les terres, écume près de la côte. Carte principale = bouée 46054 ; mini-carte du spot = direction MOP de l'heure choisie. Lit `data.js` par une balise `<script>` pour marcher en `file://` sans serveur.
- `lancer.bat` : lance `surf.py` puis ouvre la page.
- En ligne : `.github/workflows/update.yml` lance `surf.py` toutes les heures et publie `web/` sur GitHub Pages (source « GitHub Actions »). `web/data.js` n'est **pas** commité (gitignore) pour ne pas gonfler l'historique. `surf.py` sort en erreur si aucun spot n'a de prévision, pour garder la version en ligne précédente.
- PWA : `web/manifest.json`, `web/sw.js` (réseau d'abord pour la page et `data.js`, cache pour Leaflet et les polices, tuiles de carte jamais mises en cache par le SW à cause des conditions d'Esri), `web/icons/`. Le dépôt est public, la page a `noindex`.

## Sources

- Houle par spot : CDIP MOP, `https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/{ID}_forecast.nc.ascii?waveTime,waveHs,waveTp,waveDp` (80 pas de 3 h). Préfixes : `VE` (Ventura, 3 chiffres), `B` (Santa Barbara, 4 chiffres, croissant vers l'ouest), `SL` (San Luis Obispo, 3 chiffres).
- Marées : NOAA 9411340 (Santa Barbara) et 9412110 (Port San Luis), en MLLW, ft, heure GMT.
- Météo, vent, lever/coucher, température de l'eau : Open-Meteo forecast + marine, multi-coordonnées en un appel (renvoie une liste).
- Bouées NDBC : 46053, 46054, 46011 (fichiers `realtime2/*.txt`).

## Règles de notation (dans surf.py)

- Taille au spot = Hs MOP × 3,281 × **1,2** (biais : le modèle sous-estime ~20 % dans le canal, étude UCSB `aadhavr/campus-point-waves`). Fourchette affichée = ×0,75 à ×1,25.
- Note /10 = taille (4) + période (2) + marée (2) + vent (2), heures de jour seulement. Si taille < minimum du spot → note plafonnée à 2.
- Vent vs plage : angle avec l'offshore parfait (normal + 180) → offshore / side-off / sideshore / side-on / onshore.
- Forme (hollow → mushy) et surface (glassy → blown out) : règles maison, à calibrer.

## Observations terrain d'Atamaï (à respecter)

- Sands : au-dessus d'environ 5,5 ft de marée, ça devient trop haut et mou.
- Un mardi de novembre, 3 ft avec séries à 4 ft à Sands alors que DeepSwell annonçait moins : les sites sous-estiment d'environ 1 ft.
- Les houles de sud sont en grande partie bloquées par les Channel Islands pour Isla Vista ; la houle d'ouest/nord-ouest est la bonne.

## À faire en priorité

1. Lancer `python surf.py` avec le vrai réseau et corriger ce qui casse : le code n'a été testé qu'avec des données simulées au format réel.
2. Vérifier pour chaque spot la ligne « Model point … km away » : un point à plus d'environ 1 km est suspect.
3. Vérifier que la réponse `.ascii` du CDIP respecte bien la projection `?waveTime,waveHs,waveTp,waveDp` (sinon le parser lit quand même, mais la réponse est plus lourde).

## Plus tard

- Calibrer les réglages des spots au nord (Jalama → Cayucos) avec des observations réelles.
