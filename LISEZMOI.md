# Central Coast Surf

Prévisions de surf de Ventura à Cayucos (28 spots), avec une carte zoomable, une recherche et un interrupteur ft/°F ↔ m/°C.

## Lancer

Double-clic sur **`lancer.bat`** : il récupère les données (environ 15 secondes), puis ouvre la page.
Ou bien : `python surf.py`, puis ouvrir `web\index.html`.

Il faut juste Python 3.9 ou plus récent, et une connexion Internet (pour les données et le fond de carte).

**Premier lancement :** le script télécharge la liste officielle des points du modèle CDIP (≈ 750 Ko) et la garde dans `config\mop_points.csv`. Il s'en sert pour trouver tout seul le point de prévision le plus proche de chaque spot, ainsi que l'orientation de la plage.

## Sur le téléphone (en ligne)

Le site est publié par GitHub Pages et mis à jour toutes les heures par GitHub Actions (`.github/workflows/update.yml`) : le PC n'a pas besoin d'être allumé.

- Installer : ouvrir l'adresse du site, puis **iPhone (Safari)** : Partager → « Sur l'écran d'accueil » ; **Android (Chrome)** : ⋮ → « Installer l'application ».
- Forcer une mise à jour : onglet **Actions** du dépôt → « Update forecast » → **Run workflow**.
- Si le dépôt n'a reçu aucun commit pendant 60 jours, GitHub met en pause la mise à jour horaire (il prévient par mail) : bouton **Enable workflow** dans l'onglet Actions, ou faire n'importe quel commit.
- `web/data.js` n'est pas versionné : il est recréé à chaque lancement (en local par `lancer.bat`, en ligne par le workflow).

## Dossier

```
surf-central-coast\
├── surf.py              récupère les données, calcule les notes, écrit web\data.js
├── config\spots.json    les spots : position, région, réglages, fiche (en anglais)
├── config\mop_points.csv  créé au premier lancement (liste des points CDIP)
├── web\index.html       la page (carte, recherche, graphiques, unités)
├── web\data.js          généré par surf.py (ne pas modifier, pas versionné)
├── web\manifest.json, web\sw.js, web\icons\   appli installable (PWA)
├── .github\workflows\update.yml   mise à jour horaire + publication GitHub Pages
└── lancer.bat           met à jour et ouvre la page
```

## Ajouter un spot

Ajouter une entrée dans `config\spots.json` avec au minimum : `key`, `name`, `region`, `priority`, `lat`, `lon`, `tide`, `size`, `swellWin`, plus les textes de la fiche. Pas besoin de chercher le point CDIP : il est trouvé automatiquement. La ligne « Model point … km away » sur la fiche du spot permet de vérifier qu'il est bien proche.

`priority` : 1 = visible sur la carte dézoomée, 2 = visible en zoomant.

## Sources

CDIP MOP (houle devant chaque spot) · NOAA Tides (Santa Barbara 9411340, Port San Luis 9412110) · bouées NDBC 46053, 46054, 46011 · Open-Meteo (météo, vent, température de l'eau, par spot) · fond de carte satellite Esri World Imagery (étiquettes Esri / OpenStreetMap).
