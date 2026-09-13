# Validation du prototype

## Données et relations

Le snapshot MinIO contient 110 000 salariés, 16 500 prestataires, 79 833 portables,
36 667 postes fixes, 2 000 serveurs, 20 000 VM et 180 sites répartis entre 12 entités.
Le modèle vérifie les identifiants uniques, les installations, les liens aux
utilisateurs, les hôtes des VM et les implantations lors de la relecture.

Le rapport analytique couvre 30 produits et 912 500 installations. Les mesures
séparent fonctionnement des systèmes, activité des services et exécution des
applications. Une mesure absente reste inconnue ; une couverture incomplète
ne permet pas de conclure à l’inactivité.

## Contrôles automatisés

- Backend : 95 tests, dont les périmètres partiels, produits homonymes, relations,
  persistance, autorisations et publication concurrente des analyses.
- Frontend : 22 tests et compilation TypeScript/Vite.
- Génération : lecture et validation des partitions avant activation,
  relance sans doublons et maintien du rapport actif en cas d’échec.
- Notes : effacement du texte et de ses révisions ; le rollback irréversible
  échoue sans modifier la révision de la base.
- Parcours HTTP partagé : espaces, membres, coûts, dossiers, notes, export,
  isolation, droits lecteur et révocation de session sur une base de tests dédiée.

Les parcours catalogue, périmètre, inventaire, analyses et examen des installations
RHEL ont aussi été inspectés dans le navigateur. Les tests ne remplacent pas
la vérification visuelle après une modification d’interface.

## Delta Lake

- Test MinIO dédié : deux écritures concurrentes, réouverture et lecture d'une ancienne version.
- Démarrage à vide : 365 jours et 4 380 relevés de capacité générés directement en Delta ; aucun fichier Silver historique requis.
- Migration de l'inventaire : comparaison du contenu des dimensions et des 730 partitions quotidiennes des deux familles d'observations avant publication.
- Historique actif des capacités : 4 452 lignes sur 366 jours, conservant les relevés ajoutés à la démo ; résultats Spark identiques avant et après conversion.
- API contrôlée après purge et redémarrage : 30 produits, 138 500 machines, analyses RHEL et périmètres accessibles.
- Empreintes des comptes, membres, espaces, coûts, dossiers, notes et périmètres identiques avant et après bascule.

La rétention automatique destructive reste désactivée. Le test de concurrence est lancé séparément avec `TEST_DELTA_MINIO=1` ; il est ignoré dans la suite sans MinIO.

## Limites

La démonstration ne valide pas la tenue sous charge du SI réel. Les règles de
licence, coûts et droits libérables doivent être confirmés avant tout chiffrage.
Le contrat API DIGIMON et l’intégration du frontend dans sa route dédiée restent
à convenir avec son équipe. Nexora consomme uniquement l’API DIGIMON, jamais
les agents ou le Beacon directement.

Les sauvegardes externes et leur restauration ne sont pas couvertes par ces
contrôles. Le SSO et la récupération de mot de passe ne sont pas implémentés.
