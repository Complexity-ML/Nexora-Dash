# Migration Dash : état vérifié

## En place

- Application Dash/Plotly servie par Gunicorn, image Python autonome sans FastAPI.
- Services métier appelés directement par les callbacks ; contrôles des sessions, espaces, rôles et versions conservés.
- Inventaire, catalogue, licences, analyses, coûts, dossiers et notes accessibles dans Dash.
- Lecture des publications Gold sans déclenchement de Spark à chaque navigation.
- Graphiques de répartition du parc, comparaisons par filiale et système, usages quotidiens, activité des installations, licences par unité, pression des pools et classement des opportunités.
- Parc logiciel : classement des déploiements ; fiches produit avec répartition par filiale, activité, fréquence et couverture. Fiches machine avec historique d’activité par produit, versions et utilisateurs reliés.
- Vue d’ensemble : comparaison filiales × systèmes, en volumes ou en parts du parc ; clic sur les distributions pour filtrer la comparaison sur place. Les cartes de redirection intermédiaires ont été retirées.
- Navigation depuis les autres graphiques vers les éléments correspondants ; clic sur les VM vérifié dans la démonstration.
- Export CSV du catalogue et des licences : recherche et périmètre courants, toutes les pages, lignes par filiale et unité, droits revérifiés au téléchargement.
- Export HTML imprimable d’un dossier via Dash avec vérification d’accès au téléchargement.
- Catalogue consultable sans analyses Gold ; détails des licences chargés à l’ouverture et liste paginée.

- Périmètre logiciel en cartes cochables avec recherche et actions groupées, sans menu géant.
- Analyse annuelle : dispersion des usages, durée des pics et évolution relative des capacités.
- Initialisation explicite d’un lac de démonstration vide, avec validation avant publication et refus d’une seconde initialisation.
- Supervision des journées publiées et des processus de collecte et de reprise ; profil Docker `collection` autonome.

## Preuves de validation

Les tests `test_dash.py` exercent les callbacks, sessions, refus d’accès, notes, formulaires membres, navigation Plotly et export de dossier. `test_dash_charts.py` contrôle les journées manquantes et les populations non additives. `test_dash_software.py` couvre le catalogue sans Gold et la pagination des licences. `test_published_analytics.py` vérifie que la lecture ne lance ni collecte ni calcul.

`verify_dash_pages.py` construit les pages avec les services et données de la démonstration. Il ne prouve pas à lui seul que tous les états visuels sont corrects. Les tests PostgreSQL utilisent une base isolée, distincte de la démonstration.

L’installation a aussi été démarrée sur un projet Compose isolé, avec de nouveaux volumes PostgreSQL et MinIO. La connexion et l’état sans publication ont été vérifiés dans le navigateur. La commande d’initialisation a publié 12 pools et 4 380 relevés journaliers validés. Une deuxième tentative a été refusée. Les 14 pages ont ensuite été construites avec ces données via `verify_dash_pages.py` ; cela ne vaut pas une revue visuelle complète des 14 pages. L’environnement de test a été retiré après validation.

## À terminer avant clôture

- Vérification finale des guides et commandes sur une installation neuve ; les guides d’exploitation, de BI et de parcours décrivent désormais Dash et les services Python.
- Compléter les exports des autres vues et vérifier les fonctions de confort de l’ancienne interface.
- Compléter les vues économiques interactives. Le suivi des collectes est désormais accessible aux opérateurs dans la page Data Lake.
- Vérifier tous les parcours métier et graphiques dans le navigateur, avec plusieurs largeurs et des espaces à périmètre partiel.
- Vérifier visuellement l’état sans espace. L’état sans publication est vérifié sur l’installation neuve ; les deux parcours sont couverts par les tests de callbacks et de pages.
- Préparer la livraison finale et son archive source.

Le raccordement DIGIMON réel, l’intégration dans son portail et Power BI sur le réseau cible restent des validations externes. Les chiffres présentés sont fictifs et les économies sont des simulations. La migration ne doit pas être déclarée terminée sur la seule base des tests unitaires.
