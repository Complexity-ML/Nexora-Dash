# Organisation du frontend

Le frontend Nexora est une application React/Vite autonome pour la démonstration.
La cible est son intégration dans DIGIMON sur une route dédiée ; son backend Python
reste séparé et consomme l’API REST du backend Node.js DIGIMON. Le chemin définitif
et l’authentification partagée restent à convenir avec l’équipe DIGIMON.

## Découpage

Le frontend est organisé ainsi :

- `layouts/` : navigation, en-tête, espace actif et structure commune.
- `pages/` : écrans associés aux routes (inventaire, logiciels, licences, économies,
  analyses, sources, pipelines, lac, paramètres, recherche et dossiers).
- `components/` : éléments réutilisables et formulaires métier.
- `hooks/` : chargement des données et état partagé.
- `services/api/` : transport HTTP vers le backend Nexora.
- `lib/navigation/` : définition et interprétation des routes.

Le découpage doit préserver les liens existants, les périmètres des espaces, les
états de chargement et les erreurs propres à chaque source. Les pages inventaire
et recherche restent accessibles lorsque les analytics des pools sont indisponibles.

## Données et limites

La recherche traverse les logiciels suivis, machines, utilisateurs et sites.
L’inventaire est filtré et paginé côté serveur ; les détails sont chargés à
l’ouverture d’une fiche. Les systèmes et composants installés sont distincts des
pools de licences : leur présence ne suffit pas à calculer un taux d’occupation.
Les durées absentes ne sont pas converties en zéro.

## Validation

Depuis la racine :

```sh
npm --prefix frontend test
npm --prefix frontend run build
```

Contrôler aussi le parcours filiale → catégorie → fiche, le retour, la recherche
transversale, le changement d’espace, les thèmes et les petits écrans. Un build
réussi ne remplace pas cette vérification visuelle.

Les écrans sont sélectionnés dans `lib/navigation/DashboardRoutes.tsx` et chargés à la demande. `layouts/DashboardLayout.tsx` porte le cadre commun. `OverviewPage.tsx` contient la vue d’ensemble ; `SoftwarePage.tsx` et `SoftwareDetailPage.tsx` séparent catalogue et fiche. Les anciens fichiers `DashboardSections.tsx` et `DashboardPage.tsx` ont été supprimés.

Le graphique historique est isolé dans `components/dashboard/UsageHistoryChart.tsx`. Le build après découpage produit un module principal de 235 Ko (74 Ko gzip), contre environ 709 Ko (212 Ko gzip) avant extraction. Les graphiques sont chargés avec les pages qui en ont besoin ; ces tailles locales ne sont pas une mesure de latence sur le réseau de production.

## Catalogue et périmètre analytique

`SoftwarePage` réunit les produits de l’inventaire par `software_id` et rattache les
historiques via `license_pool_id`, avec recherche, filtres et pagination de 12 cartes. Une installation
n’implique pas un historique d’usage. `LicensesPage` affiche séparément installations,
droits et capacité des pools ; les unités ne sont pas additionnées.
Les produits homonymes conservent leurs identités distinctes. Seules les entrées
anciennes sans identifiant sont synthétisées à partir des noms non ambigus.
Les recherches et liens d’installations transportent l’identifiant stable du produit.

La construction du pipeline n’ouvre plus de session Spark. Une lecture du catalogue
ou du cache Gold n’en a pas besoin ; Spark démarre au premier calcul effectif.
Les caches restent vérifiés contre la révision des données et les seuils d’analyse.

La suppression de la recherche d’inventaire dispose d’une cible de 44 × 44 px.
Le sélecteur de périmètre annuel réutilise `CatalogFilter` et limite la hauteur du
menu, plutôt que d’ouvrir le menu natif du système sur toute la largeur.

### Actualisation et mesures du catalogue

`useBusinessResource` conserve les données du même chemin pendant une actualisation. Un changement d’espace masque immédiatement les données de l’ancien chemin. La page Licences réserve la place du statut de chargement et conserve ses lignes pendant une actualisation.

Les cartes du catalogue affichent les installations et l’analyse Gold des usages par machine. Les cartes ont une seule action, « Voir les machines ». Les historiques de capacité restent dans les pages d’analyse des pools : leur taux n’est pas un taux d’utilisation des installations. Sans observations par machine, aucune inactivité n’est déduite de la seule présence du logiciel.

La page Licences distingue les droits déclarés des produits à qualifier. Les détails s’ouvrent dans le tableau, sans redirection vers le parc logiciel. Le catalogue attend les réponses inventaire et usages avant de remplacer ses emplacements de chargement, pour éviter une succession de listes partielles.

Le menu latéral peut être replié sur ordinateur avec le bouton près du logo. Les icônes gardent leurs noms accessibles et leurs infobulles. Le choix est conservé localement ; le menu mobile garde son comportement de tiroir.
