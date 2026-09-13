# Architecture et flux de données

## Vue d'ensemble

```text
SCCM / Flexera One → Beacon
      │ collecte existante
      ▼
DIGIMON API Node.js
      │ payload opérationnel inconnu
      ▼
HttpDigimonConnector ───── MockDigimonConnector (démo)
      │ map_digimon_payload()
      ▼
Modèle SAM canonique
      │
      ├── Bronze : enveloppe du payload source, Parquet
      ├── Silver : données normalisées, Delta partitionné par date
      └── PySpark : tendances, sous-utilisation, saturation
                         │
                         ▼
                 Gold Analytics, Delta
                         │
                         ▼
                  FastAPI /api/v1
                         │ DTO SAM uniquement
                         ▼
                    SAMUI React
```

## Responsabilités

| Composant        | Responsabilité                                         | Ne doit pas faire                               |
| ---------------- | ------------------------------------------------------ | ----------------------------------------------- |
| DIGIMON          | Collecte opérationnelle SCCM/FlexLM et exposition HTTP | Porter les règles analytiques SAMUI             |
| Adapter DIGIMON  | Transport HTTP et traduction du payload                | Propager le format DIGIMON hors du connecteur   |
| Modèle canonique | Vocabulaire stable SAM                                 | Dépendre d'un nom de champ fournisseur          |
| ObjectStore      | Persistance S3-compatible                              | Coupler les services métier à MinIO             |
| PySpark          | Production déterministe des données Gold               | Prendre des décisions de suppression            |
| FastAPI          | Façade stable pour le frontend                         | Exposer des credentials ou le payload brut      |
| React            | Présentation et interaction                            | Recalculer les règles métier ou appeler DIGIMON |

## Modèle de référence

Les classes `SoftwareProduct`, `LicensePool`, `LicenseStock`, `LicenseUsage` et `UsageSnapshot` décrivent les données normalisées. `Trend`, `InactiveCandidate`, `SaturationRisk` et `AnalyticsSummary` décrivent les produits analytiques.

Les interfaces TypeScript sont des miroirs de transport. Une évolution de contrat commence côté Pydantic, puis doit être répercutée dans le client TypeScript. À terme, leur génération depuis le schéma OpenAPI supprimera cette étape manuelle.

## Couches de données

### Bronze

- Clé : `bronze/digimon/date=YYYY-MM-DD/<snapshot-id>.parquet`.
- Contenu : identifiant, horodatage et payload source sérialisé.
- But : audit et possibilité de rejouer le mapping.

### Silver

- Clé : `silver/pool_usage` (table Delta, partition `observation_date`).
- Contenu : lignes `LicenseUsage` canoniques.
- But : entrée stable des traitements Spark.

### Gold

- Clé MVP : `gold/analytics/latest` (table Delta).
- Contenu : synthèse et produits analytiques sérialisés.
- But : données prêtes à exposer par l'API.

delta-rs lit la version Delta sélectionnée et transmet les capacités à Spark via Arrow. Les lecteurs d'inventaire utilisent des références de tables versionnées dans le manifest publié. La compatibilité Parquet reste réservée aux anciennes générations et à leur migration. Voir [Delta Lake](delta-lake.md) pour la rétention et la maintenance.

## Analytics déterministes

- **Tendance** : moyenne, maximum, P95 approximatif, taux d'utilisation et variation entre premier et dernier relevé.
- **Sous-utilisation** : seuil configurable, réserve configurable, durée observée et confiance croissante avec l'historique.
- **Saturation** : croissance journalière linéaire, capacité restante et date estimée lorsque la pente est positive.

Ces résultats donnent un signal d'aide à la décision. Ils ne constituent ni une prévision ML ni une décision contractuelle automatique.
