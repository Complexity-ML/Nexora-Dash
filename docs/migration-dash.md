# Migration Dash : état vérifié

## En place

- Application Dash/Plotly servie par Gunicorn, image Python autonome sans FastAPI.
- Services métier appelés directement par les callbacks ; contrôles des sessions, espaces, rôles et versions conservés.
- Inventaire, catalogue, licences, analyses, coûts, dossiers et notes accessibles dans Dash.
- Lecture des publications Gold sans déclenchement de Spark à chaque navigation.
- Graphiques de répartition du parc, comparaisons par filiale et système, usages quotidiens, activité des installations, licences par unité, pression des pools et classement des opportunités.
- Navigation depuis un graphique vers les éléments correspondants ; clic sur les VM vérifié dans la démonstration.
- Export HTML imprimable d’un dossier via Dash avec vérification d’accès au téléchargement.
- Catalogue consultable sans analyses Gold ; détails des licences chargés à l’ouverture et liste paginée.

- Périmètre logiciel en cartes cochables avec recherche et actions groupées, sans menu géant.
- Analyse annuelle : dispersion des usages, durée des pics et évolution relative des capacités.
- Supervision des journées publiées et des processus de collecte et de reprise ; profil Docker `collection` autonome.

## Preuves de validation

Les tests `test_dash.py` exercent les callbacks, sessions, refus d’accès, notes, formulaires membres, navigation Plotly et export de dossier. `test_dash_charts.py` contrôle les journées manquantes et les populations non additives. `test_dash_software.py` couvre le catalogue sans Gold et la pagination des licences. `test_published_analytics.py` vérifie que la lecture ne lance ni collecte ni calcul.

`verify_dash_pages.py` construit les pages avec les services et données de la démonstration. Il ne prouve pas à lui seul que tous les états visuels sont corrects. Les tests PostgreSQL utilisent une base isolée, distincte de la démonstration.

## À terminer avant clôture

- Vérification finale des guides et commandes sur une installation neuve ; les guides d’exploitation, de BI et de parcours décrivent désormais Dash et les services Python.
- Vérification des exports tabulaires et autres fonctions de confort de l’ancienne interface.
- Compléter les vues économiques interactives. Le suivi des collectes est désormais accessible aux opérateurs dans la page Data Lake.
- Vérifier tous les parcours métier et graphiques dans le navigateur, avec plusieurs largeurs et des espaces à périmètre partiel.
- Vérifier visuellement les états sans espace ou sans publication ; les parcours sont désormais couverts par les tests de callbacks et de pages.
- Valider le démarrage d’une installation neuve avec ses données de démonstration.
- Préparer la livraison finale et son archive source.

Le raccordement DIGIMON réel, l’intégration dans son portail et Power BI sur le réseau cible restent des validations externes. Les chiffres présentés sont fictifs et les économies sont des simulations. La migration ne doit pas être déclarée terminée sur la seule base des tests unitaires.
