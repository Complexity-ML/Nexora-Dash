# CLI Nexora

Dans Docker, utiliser `nexora`. Depuis une installation Python locale, utiliser
`python -m app.cli` depuis `nexora/`. L’aide est disponible à chaque niveau :

```sh
docker compose exec dash nexora --help
docker compose exec dash nexora collect --help
docker compose exec dash nexora collect status --help
```

## Exploitation

| Groupe | Commandes |
| --- | --- |
| `collect` | `run`, `recover`, `status` |
| `lake` | `compact`, `retention`, `prune-index`, `rebuild-summary`, `import` |
| `bi` | `policy`, `issue`, `revoke`, `reconcile` |
| `backup` | `hold` |

Les paramètres et protections des services sont conservés. Par exemple,
`nexora lake prune-index` prépare un plan ; `--apply` applique la suppression
des projections non référencées. `nexora lake compact` reste sans modification
sans `--apply`. Lire l’aide de chaque commande avant une opération de maintenance.

## Développement uniquement

L’image par défaut ne contient ni les générateurs de démo, ni les tests, ni les
convertisseurs historiques, ni pytest. Ils sont ajoutés uniquement par la cible
Docker `development` :

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml build dash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps dash nexora dev --help
```

Les groupes `dev demo`, `dev verify` et `dev migrate` regroupent respectivement
les données fictives, les vérifications et les conversions historiques.
`nexora dev verify tests` utilise une base jetable distincte de la base métier.
Le code de ces outils reste versionné dans `nexora/devtools/` pour reproduire les
vérifications ; il n’est pas copié dans l’image de production.

Le dossier `nexora/migrations/versions` reste livré : Alembic en a besoin pour
créer et faire évoluer le schéma PostgreSQL. Il ne contient pas les conversions
historiques du lac.
