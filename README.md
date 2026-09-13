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

Une installation neuve ne contient pas automatiquement le scénario d’entreprise. Le stockage et les traitements doivent être initialisés avec les scripts de démonstration avant de consulter les analyses.

## Développement

Le code Dash se trouve dans `backend/app/dash_ui`, les services métier dans `backend/app/business`, et les traitements dans `backend/app/services` et `backend/app/collection`.

```sh
cd backend
pip install -r requirements.txt
python -m app.dash_ui.app
```

Les tests nécessitent PostgreSQL et, pour les tests Spark, Java. Utiliser une base de test isolée ; ne jamais lancer la suite sur les données de démonstration à conserver.

## État de la migration

Migration en cours : les parcours métier ont été portés vers Dash et testés localement. La finition visuelle, la validation complète de la nouvelle image Docker et la mise à jour de toute la documentation restent en cours. Certains guides et scripts hérités décrivent encore l’ancienne application ; ils ne constituent pas le contrat de cette version.

Les données affichées sont fictives. Le raccordement DIGIMON réel et la validation Power BI sur le réseau cible restent à effectuer. Les économies affichées sont des simulations, pas des gains réalisés.
