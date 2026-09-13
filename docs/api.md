# API SAM Analytics

Base locale : `http://localhost:8000/api/v1`. Le schéma exécutable est disponible dans Swagger UI à `/docs` et au format OpenAPI à `/openapi.json`.

## Endpoints

| Méthode | Route                | Réponse               | Description                                       |
| ------- | -------------------- | --------------------- | ------------------------------------------------- |
| `GET`   | `/live`              | `LicenseUsage[]`      | Usage courant obtenu via le connecteur actif      |
| `GET`   | `/stock`             | `LicenseStock[]`      | Capacité, consommation et disponibilité courantes |
| `GET`   | `/history`           | `Trend[]`             | Historique journalier embarqué dans les tendances |
| `GET`   | `/trends`            | `Trend[]`             | Agrégats analytiques par pool                     |
| `GET`   | `/inactive`          | `InactiveCandidate[]` | Pools sous le seuil configurable, à examiner      |
| `GET`   | `/analytics/summary` | `AnalyticsSummary`    | Synthèse utilisée par le dashboard                |
| `POST`  | `/sync`              | `UsageSnapshot`       | Capture et persiste un nouveau snapshot           |
| `GET`   | `/health`            | objet de statut       | Vérification de vie hors préfixe `/api/v1`        |

## Exemples

```sh
curl http://localhost:8000/api/v1/analytics/summary
curl -X POST http://localhost:8000/api/v1/sync
curl http://localhost:8000/health
```

Extrait représentatif d'une synthèse :

```json
{
  "generated_at": "2026-09-11T12:00:00Z",
  "total_capacity": 3600,
  "total_used": 1700,
  "total_available": 1900,
  "utilization_rate": 0.4722,
  "pools_at_risk": 1,
  "pools_total": 3,
  "recovery_potential": 520,
  "trends": [],
  "inactive": [],
  "risks": []
}
```

Les nombres ci-dessus illustrent la structure et ne constituent pas une fixture contractuelle.

## Stabilité et erreurs

- Les réponses publiques reposent sur les modèles canoniques Pydantic.
- Le frontend centralise toutes les requêtes dans `frontend/src/services/api/analytics.ts`.
- Une erreur de transport ou d'analyse est affichée comme indisponibilité ; elle n'est pas remplacée silencieusement par de fausses données.
- `POST /sync` est destiné au déclenchement manuel du MVP. Une authentification et une autorisation sont requises avant toute exposition en production.

## Évolution du contrat

1. Modifier le modèle Pydantic canonique.
2. Vérifier `/openapi.json` et les tests FastAPI.
3. Répercuter ou générer les DTO TypeScript.
4. Adapter la vue sans introduire de format DIGIMON dans React.

### Capacités variables

`Trend.capacity` est la capacité du dernier relevé du pool. Les risques et le
potentiel de récupération utilisent cette capacité actuelle. Le taux moyen
`Trend.utilization_rate` est la moyenne des taux `used / capacity` de chaque
relevé (zéro lorsque la capacité est nulle), et non le ratio avec la capacité
maximale historique.

Chaque point `Trend.daily` contient `date`, `used` et `capacity` : la capacité
est celle du relevé portant le pic d'utilisation du jour. À pic égal, le relevé
le plus récent est retenu. Le graphique agrège les usages et capacités des pools
présents à cette date ; il ne réutilise pas le stock actuel pour les dates passées.

### État de la plateforme

`GET /api/v1/platform` expose le mode actif, l’heure de vérification, les seuils
analytiques et l’inventaire des couches Bronze/Silver/Gold. Chaque couche contient
le nombre réel d’objets, les bornes de dates des partitions et au plus 12 clés
récentes dans l’ordre lexicographique. Aucun identifiant S3 ou DIGIMON n’est exposé.
Ce relevé n’est pas un historique d’exécutions ni une preuve de surveillance continue.

### Suppression d’un dossier

`DELETE /api/v1/business/workspaces/{wid}/cases/{cid}` reçoit `{ "version": 1 }`. Un administrateur ou analyste de cet espace peut supprimer définitivement le dossier et tous ses événements, dont les notes. Une version périmée renvoie 409, un dossier hors espace 404 et un lecteur 403. La suppression ne modifie ni les coûts partagés ni les données du lac. L’interface demande une confirmation dans la fiche du dossier.
