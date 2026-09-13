# Delta Lake

Silver et Gold utilisent Delta Lake. Les anciens fichiers Parquet restent lisibles uniquement pour migrer une génération existante.

## Collecte

Nexora consomme l'API REST DIGIMON en batch quotidien après la mise à disposition des relevés. DIGIMON centralise les remontées des agents ; Nexora ne se raccorde pas au Beacon. L'heure de collecte dépend de la disponibilité effective des données, pas seulement de l'heure de passage des agents.

Les payloads Bronze restent archivés. Les tables Silver et Gold passent au protocole Delta, avec une référence de table et de version dans les manifests publiés. Les lecteurs utilisent le journal Delta et ne parcourent jamais directement ses fichiers Parquet.

Le jeu de démonstration comporte 92 345 000 observations annuelles de pools liées aux machines, complétées par 241 082 500 observations annuelles de systèmes et applications, soit 333 427 500 observations. Ce volume de lignes ne permet pas à lui seul de déduire une taille en Go ou un temps de traitement.

## Partitionnement

Les dimensions d'état courant (machines, utilisateurs, sites et produits) sont sans partition temporelle. Un inventaire complet remplace leur contenu dans une transaction Delta ; un flux incrémental nécessitera un `MERGE` fondé sur les identifiants stables du contrat DIGIMON.

Les observations historiques sont partitionnées par `observation_date`. Le regroupement mensuel des archives Bronze ou des observations sera décidé d'après les tailles mesurées et les besoins de rejeu. Aucune hypothèse de 30 Go par mois n'est retenue sans mesure. Pays et filiale ne deviennent pas automatiquement des partitions : le filtrage, la taille des groupes et leurs changements d'affectation doivent être évalués.

## Fichiers et requêtes

Les écritures sont regroupées par relevé quotidien. La maintenance contrôle le nombre et la taille des fichiers avant de déclencher une compaction. Une cible initiale de 128 Mo pourra être mesurée sur le jeu réel ; elle ne constitue pas une taille minimale à imposer aux petites partitions.

Le Z-Ordering sera évalué sur les identifiants réellement filtrés, comme `machine_id` ou `software_id`, si les statistiques et mesures montrent un bénéfice. Il ne sera pas activé sur une colonne déjà utilisée comme partition ni sur un seuil arbitraire de 10 ou 20 Go.

Avec l'API Python Delta Spark, les opérations sont `table.optimize().executeCompaction()` ou `table.optimize().executeZOrderBy("machine_id")`. La chaîne `zorderBy(...).execute()` n'est pas cette API.

## Rétention

Une vérification hebdomadaire des fichiers périmés est prévue. La purge effective reste désactivée tant que la protection des versions référencées par les manifests et les analyses en cours n'est pas vérifiée.

`VACUUM` supprime les fichiers devenus inutilisés par la table et dépassant la durée de rétention. Il ne supprime pas les observations métier encore présentes dans la table, même anciennes. La rétention par défaut des fichiers supprimés est de sept jours ; celle du journal est de trente jours. Ces valeurs ne garantissent pas la lisibilité des anciennes versions après purge.

Une version encore référencée doit rester lisible. Il faut coordonner publication, traitements et maintenance avant toute suppression ; un contrôle isolé suivi d'une purge laisse une course possible avec une nouvelle publication. Ne jamais désactiver la vérification minimale de rétention pour gagner de la place.

## Schémas et accès

Le contrat Silver est validé avant écriture. Les nouvelles colonnes font l'objet d'une évolution explicite et testée ; `mergeSchema` n'est pas activé globalement. Un changement de type incompatible doit être traité, pas masqué.

Les identités et accès sont séparés dès le raccordement. Les consommateurs BI accèdent aux résultats Gold autorisés, avec les restrictions de périmètre nécessaires. Gold ne signifie pas automatiquement données anonymisées.

L'archivage à froid de Bronze dépend du stockage cible et du besoin de relecture. Aucune règle Glacier ou Azure Archive ne s'applique automatiquement au MinIO local. Ne pas déplacer ou supprimer les fichiers internes des tables Delta avec une règle de cycle de vie indépendante de leur journal.

## Références

- [Maintenance et rétention Delta](https://docs.delta.io/delta-utility/)
- [Compaction et Z-Ordering](https://docs.delta.io/optimizations-oss/)
- [Validation et évolution des schémas](https://docs.delta.io/delta-batch/)
