# Nexora-Dash

Prototype d’analyse du parc logiciel et matériel avec Dash/Plotly, Python, PySpark et Delta Lake sur MinIO.

## Architecture

```text
Agents / Beacon → DIGIMON (API REST)
                         ↓
               Collecteur Python Nexora
                         ↓
             Historique / Silver Delta Lake
                         ↓
                Traitements PySpark
                         ↓
                  Résultats Gold
                         ↓
             Services Python → Dash/Plotly
```

Nexora consomme DIGIMON ; il ne se connecte pas directement aux agents ou au Beacon. L’interface Dash appelle les services Python avec les contrôles d’accès métier. Elle lit les résultats publiés sans lancer Spark à chaque interaction. FastAPI et le frontend React ne font pas partie de cette application.

## Fonctions du prototype

- Exploration croisée des machines, utilisateurs et implantations, avec filtres et accès aux fiches.
- Catalogue logiciel, licences, historique de capacité et simulations économiques.
- Espaces partagés, périmètres, rôles, dossiers, coûts et notes.
- Qualité des dimensions d’inventaire et consultation des métadonnées du lac.
- Collecte et reprise indépendantes de l’interface.

## Démarrage local

Prérequis : Docker Compose.

```sh
python3 workflow/init-local-env.py
docker compose up -d --build
```

Interface : http://localhost:8050. Console MinIO : http://localhost:9001.
Les secrets restent dans le fichier `.env` local, exclu de Git. Les comptes de démonstration utilisent `SAM_DEMO_PASSWORD`.

Sur une installation neuve, la connexion fonctionne avant la publication des analyses. Pour créer le petit jeu de référence (12 pools, un an d’historique fictif et son inventaire) :

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml build dash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps -e DEMO_TOOLS_ENABLED=true dash nexora dev demo initialize
```

Cette commande prépare une génération séparée, valide les résultats puis les publie. Elle refuse un lac déjà alimenté et ne supprime pas de données. Actualiser ensuite la page Dash. Le scénario d’entreprise de 138 500 machines constitue un chargement distinct, plus volumineux ; il n’est pas lancé automatiquement.

Comptes disponibles : `admin@sam.demo`, `analyst@sam.demo` et `reader@sam.demo`. Leur mot de passe est la valeur locale `SAM_DEMO_PASSWORD` générée dans `.env`. Ne pas exposer ces comptes de démonstration sur Internet.

## Développement

Le code Dash se trouve dans `nexora/app/dash_ui`, les services métier dans `nexora/app/business`, et les traitements dans `nexora/app/services` et `nexora/app/collection`.

```sh
cd nexora
pip install -r requirements.txt
python -m app.dash_ui.app
```

Les tests nécessitent PostgreSQL et, pour les tests Spark, Java. Utiliser une base de test isolée ; ne jamais lancer la suite sur les données de démonstration à conserver.

## État de la migration

Migration en cours : les parcours métier ont été portés vers Dash et testés localement. La vérification complète des parcours et les finitions restent en cours. Les preuves de validation et les fonctions restant à terminer sont détaillées dans [le suivi de migration](docs/migration-dash.md).

Les données affichées sont fictives. Le raccordement DIGIMON réel et la validation Power BI sur le réseau cible restent à effectuer. Les économies affichées sont des simulations, pas des gains réalisés.

Les commandes d’exploitation sont décrites dans le [guide CLI](docs/cli.md).
