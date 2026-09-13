# Raccordement DIGIMON

Le contrat réel de l'API Node.js DIGIMON n'est pas connu. Le chemin présent dans le connecteur est donc un placeholder, pas une route supposée réelle.

## Frontière d'intégration

Tous les détails fournisseur doivent rester dans `backend/app/connectors/digimon.py` :

- `HttpDigimonConnector.get_raw_snapshot()` : URL, méthode, paramètres et authentification serveur ;
- `map_digimon_payload()` : traduction du payload vers `UsageSnapshot`, `LicenseUsage` et `LicenseStock`.

Spark, le stockage Silver/Gold, FastAPI et React ne doivent jamais importer un DTO DIGIMON.

## Procédure

1. Obtenir le contrat OpenAPI ou des exemples anonymisés de DIGIMON.
2. Inventorier les routes disponibles pour usage, stock et détails.
3. Définir le mécanisme d'authentification côté backend : compte technique, OAuth2 ou mTLS selon le SI.
4. Implémenter l'appel HTTP dans `HttpDigimonConnector` sans journaliser de secret.
5. Modifier uniquement `map_digimon_payload()` pour produire le modèle canonique.
6. Ajouter des fixtures de payload brut anonymisées et des tests de mapping.
7. Tester d'abord avec un bucket dédié, puis définir `SAM_DATA_SOURCE=digimon`.
8. Valider la disponibilité quotidienne avec l’adaptateur ci-dessous, puis exercer la collecte journalisée dans un namespace isolé. Vérifier Bronze, contrôles, versions Silver/Gold et publication avant toute activation du service.

## Mapping intermédiaire actuel

Le mock documente volontairement un DTO minimal :

```json
{
  "capturedAt": "2026-09-11T12:00:00Z",
  "provider": "digimon-mock",
  "pools": [
    {
      "poolKey": "flex-cad",
      "product": { "key": "autodesk-cad", "name": "Autodesk Product Design" },
      "entitlement": 800,
      "consumed": 245
    }
  ]
}
```

Ce format n'est pas un engagement sur DIGIMON. Il sert uniquement à exercer le pipeline complet en développement.

## Validation attendue

- timestamps avec timezone et granularité connues ;
- identifiants de pool et de logiciel stables ;
- capacité et consommation non négatives ;
- règle documentée lorsque `used > capacity` ;
- sémantique des utilisateurs et machines optionnels ;
- pagination, timeout et reprise sur erreur définis ;
- données sensibles identifiées avant conservation en Bronze.

## Secrets

Les secrets DIGIMON appartiennent exclusivement à l'environnement backend ou à un gestionnaire de secrets. Ils ne doivent être présents ni dans Git, ni dans un fichier `.env.example`, ni dans `VITE_SAM_API_BASE_URL`.

## Unicité des pools et pagination

Le mapping du snapshot intermédiaire refuse plusieurs lignes portant le même
`poolKey`, même si leurs valeurs sont identiques. Dans la collecte journalisée,
le payload complet est conservé en Bronze, puis le lot est rejeté avant Silver ;
la publication précédente reste active. Une déduplication silencieuse masquerait
un chevauchement de pages ou un mélange de versions source.

Ce contrôle suppose un total par pool dans ce DTO. Si DIGIMON fournit des lignes
par feature, serveur ou autre dimension, l’adaptateur devra définir leur clé et
leur agrégation avant de produire ce snapshot. La pagination réelle doit encore
garantir une révision stable entre pages, un curseur sans boucle et un total de
lignes vérifiable ; ce contrôle d’unicité seul ne garantit pas la complétude.

## Quantités du snapshot de pools

Dans le DTO intermédiaire, capacités et usages de pools sont des entiers non
négatifs. Les encodages `10`, `10.0` et `"10"` sont acceptés sans changement de
valeur. Une valeur fractionnaire n’est jamais tronquée ; les booléens, valeurs
absentes, négatives et non finies sont rejetés. La collecte journalisée conserve
le payload JSON valide en Bronze avant ce contrôle, puis refuse sa publication.
Un nombre non fini n’étant pas du JSON valide, il est refusé dès l’encodage.

Si une métrique source emploie réellement des fractions, son unité et sa précision
devront être modélisées explicitement avant de l’intégrer ; elle ne doit pas être
convertie arbitrairement en capacité entière de pool.

Les champs obligatoires manquants et une structure de liste de pools invalide
produisent une erreur de validation explicite. En mode journalisé, le lot est
archivé puis marqué `INVALID_ARTIFACT`, sans sortie Silver ni nouvelle publication.
Il ne rejoint pas la file des erreurs techniques à reprendre automatiquement.
Les tests vérifient notamment une capacité manquante, un produit absent et une
liste de pools nulle. La correction doit provenir d’un payload conforme avec une
identité de révision cohérente, sans modifier silencieusement le Bronze archivé.


## Contrat de disponibilité pour la collecte quotidienne

Le service `scripts.collect_daily` attend un adaptateur implémentant
`DailySource.ready_snapshot(day)` (`app/collection/daily.py`). Ce protocole est
interne à Nexora : il ne présume ni une route REST ni les noms de champs DIGIMON.

- `None` signifie que le relevé complet de cette journée n’est pas encore prêt.
  Il est réinterrogé ; aucune journée vide n’est publiée à sa place.
- `ReadySnapshot` contient la journée demandée, un identifiant stable de relevé,
  une révision explicite et le payload complet correspondant.
- Une erreur de transport reste une erreur, pas une réponse `None`. Elle doit
  permettre une nouvelle tentative sans faire passer une panne pour une attente.

L’heure de collecte des agents n’est pas une preuve de disponibilité de l’API.
L’adaptateur doit attendre la fin de consolidation DIGIMON. Il ne contacte pas
les agents ou le Beacon directement.

| À préciser avec DIGIMON | Preuve à fournir dans un exemple ou le contrat |
| --- | --- |
| Journée métier et fuseau | À quelle journée appartient le relevé rendu disponible ? |
| Fin de consolidation | Champ ou mécanisme distinguant un relevé complet d’un relevé en cours |
| Révision | Même révision sur toutes les pages ; nouvelle révision lors d’une correction |
| Ordre des corrections | Comment reconnaître une réponse périmée reçue après une correction ? |
| Pagination | Curseur terminal, total attendu, absence de boucle et révision commune |
| Couverture | Filiales et produits attendus, absences explicites et totaux de contrôle |
| Suppressions | Distinguer une disparition métier d’une page ou filiale non remontée |
| Historique disponible | Durée pendant laquelle une journée ou révision peut être relue |

Si DIGIMON expose seulement l’état courant, le rattrapage ne peut pas reconstruire
les journées antérieures jamais archivées. Le Bronze déjà conservé permet de
reprendre un traitement ; il ne recrée pas un relevé source qui n’a jamais existé
localement. Les révisions opaques ne sont pas triées lexicalement pour inventer
leur ordre.

Avant de brancher le service, tester : attente puis disponibilité, panne réseau,
réponse répétée, correction, réponse périmée, changement de révision entre pages,
page manquante et filiale absente. Les cas d’ordre des révisions et de pagination
restent à implémenter selon le contrat réel. Les tests actuels du worker valident
le protocole interne sur fixtures, pas ces garanties côté DIGIMON.
