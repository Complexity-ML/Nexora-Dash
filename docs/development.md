# Développement local

Le dossier `nexora/` contient toute l’application Python, y compris l’interface Dash.

## Docker

```sh
python3 workflow/init-local-env.py
docker compose up -d --build
```

Dash : http://localhost:8050. MinIO : http://localhost:9001. PostgreSQL reste sur le réseau interne. Les secrets générés sont dans `.env`, exclu de Git. Configurer les identifiants MinIO pour tout environnement partagé.

L’image démarre les migrations PostgreSQL puis Gunicorn sur `app.main:server`. La clé de session est conservée dans le volume `dash-session`. Préserver ce volume lors des mises à jour pour conserver les sessions. Les cookies doivent être sécurisés (`DASH_COOKIE_SECURE=true`) derrière HTTPS.

## Python local

```sh
cd nexora
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Configurer les variables de `.env.example` pour PostgreSQL et MinIO. Pour une exécution hors conteneur, définir `DASH_SECRET_FILE` vers un fichier local accessible en écriture. Ensuite :

```sh
alembic upgrade head
python -m app.dash_ui.app
```

La base et le lac doivent être initialisés séparément. L’interface ne fabrique pas de résultats lors d’une consultation. Les scripts de collecte et de génération se trouvent dans `nexora/scripts/`.

## Tests

Utiliser une base PostgreSQL jetable et distincte de la démonstration. Définir `DATABASE_URL` et `BUSINESS_TEST_DATABASE_URL` vers cette base, puis :

```sh
cd nexora
alembic upgrade head
pytest -q
```

Java est nécessaire aux tests Spark. Les tests MinIO demandant une configuration explicite peuvent être ignorés lorsqu’elle est absente. Le rendu visuel reste à vérifier dans le navigateur, avec les menus ouverts et plusieurs largeurs d’écran.
