# Installation et développement

## Option recommandée : Docker Compose

Prérequis : Docker avec le plugin Compose.

```sh
cp frontend/.env.example frontend/.env.local
docker compose up --build
```

Services disponibles :

| Service       | Adresse                 | Rôle                           |
| ------------- | ----------------------- | ------------------------------ |
| SAMUI         | `http://localhost:5173` | Interface web                  |
| FastAPI       | `http://localhost:8000` | API et `/docs` OpenAPI         |
| MinIO S3      | `http://localhost:9000` | Endpoint objet                 |
| MinIO Console | `http://localhost:9001` | Inspection locale des datasets |

Les identifiants MinIO du Compose sont publics et destinés exclusivement au développement local.

## Lancement manuel

MinIO doit déjà être accessible.

```sh
# Terminal backend
cd backend
cp .env.example .env
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal frontend, depuis la racine
cp frontend/.env.example frontend/.env.local
npm --prefix frontend install
npm --prefix frontend run dev
```

Le backend nécessite Java pour exécuter PySpark. L'image `backend/Dockerfile` installe un runtime Java headless.

## Variables backend

| Variable                     | Défaut                  | Description                                     |
| ---------------------------- | ----------------------- | ----------------------------------------------- |
| `SAM_DATA_SOURCE`            | `mock`                  | `mock` ou `digimon`                             |
| `DIGIMON_BASE_URL`           | vide                    | URL serveur DIGIMON, jamais exposée au frontend |
| `DIGIMON_TIMEOUT`            | `10`                    | Timeout HTTP en secondes                        |
| `S3_ENDPOINT_URL`            | `http://localhost:9000` | Endpoint S3/MinIO                               |
| `S3_ACCESS_KEY`              | local                   | Clé S3 serveur                                  |
| `S3_SECRET_KEY`              | local                   | Secret S3 serveur                               |
| `S3_BUCKET`                  | `sam-data`              | Bucket Bronze/Silver/Gold                       |
| `S3_REGION`                  | `us-east-1`             | Région client S3                                |
| `SPARK_MASTER`               | `local[*]`              | Master Spark local ou distant                   |
| `UNDERUTILIZATION_THRESHOLD` | `0.35`                  | Seuil moyen de sous-utilisation                 |
| `RECOVERY_BUFFER_RATE`       | `0.10`                  | Réserve appliquée au maximum observé            |
| `CORS_ORIGINS`               | frontend local          | Origines autorisées, séparées par des virgules  |

Le frontend ne reçoit que `VITE_SAM_API_BASE_URL`. Toute variable `VITE_*` est intégrée au bundle public : ne jamais y placer un token, mot de passe ou certificat.

## Mode démonstration

Avec `SAM_DATA_SOURCE=mock`, le premier appel analytique initialise 120 jours si Silver est vide. Les appels suivants réutilisent cet historique. En mode `digimon`, cette initialisation est désactivée et aucune donnée artificielle n'est créée.

Pour repartir de zéro avec Docker :

```sh
docker compose down -v
docker compose up --build
```

## Contrôles

```sh
(cd backend && pytest)
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
docker compose config
```
