# Publications BI et accès au stockage

Nexora-Dash n’expose plus de routes REST BI. La préparation des publications Gold, les contrôles d’audience et les services Python de lecture sont conservés. La connexion Power BI sur le réseau cible reste à finaliser et à tester.

## Compte S3 dédié

Le générateur `scripts.bi_s3_policy` produit une politique de lecture limitée à un préfixe Gold choisi. Un administrateur doit créer le compte technique et lui attacher cette seule politique. Les identifiants administrateur MinIO ne doivent pas être fournis à la BI.

```sh
python -m scripts.bi_s3_policy --bucket nexora-lake --prefix demo/gold/bi > /tmp/nexora-bi-policy.json
```

La commande ne crée ni compte, ni table, ni connexion Power BI. Les espaces Nexora ne filtrent pas automatiquement les lectures S3 : publier un préfixe correspondant à chaque audience autorisée. Les secrets restent dans le gestionnaire de secrets, pas dans Git ou les rapports.

Une table Delta se lit avec son journal et sa version, pas en concaténant tous les fichiers Parquet du dossier. Le moteur ou connecteur de lecture compatible avec l’environnement BI doit être choisi et validé séparément. Les manifestes internes ne sont pas un catalogue public.

## Instantanés Gold

Les modules `app.bi.snapshot`, `app.bi.inventory_snapshot` et `app.bi.license_snapshot` préparent des publications autonomes. Le catalogue conserve la sélection, les références de provenance et l’empreinte du manifeste. L’activation vérifie la publication attendue pour éviter qu’une mise à jour concurrente soit écrasée.

| Table | Contenu |
| --- | --- |
| `pool_usage` | Journées, pools, capacités et usages ; pas les installations |
| `inventory_counts` | Comptages agrégés d’inventaire dans la sélection autorisée |
| `license_entitlements` | Quantités et unités des droits reçus, avec identités et filiales |

Ne pas additionner des unités différentes. Les quantités manquantes restent absentes. L’inclusion des licences globales nécessite une décision explicite lors de la préparation (`include_global=True`) ; elle ne doit pas les dupliquer entre filiales. Les exclusions sont conservées dans le manifeste.

## Services Python de lecture

`app.bi.reader_service.current_publication(token)` résout la publication de l’audience portée par le jeton. `read_snapshot(snapshot_id, token)` retourne sa description vérifiée. Avec `table_name`, la même fonction produit le CSV de l’une des trois tables autorisées.

Ces services sont désactivés tant que `BI_ENABLED=false`. `BI_NAMESPACE` détermine le namespace côté serveur. Le lecteur ne choisit pas une autre audience avec un filtre. Un jeton absent, invalide ou révoqué est refusé. Si la publication a changé, le lecteur doit résoudre à nouveau le catalogue ; il ne mélange pas les deux publications.

Le service vérifie les métadonnées, le schéma et le nombre de lignes selon l’opération. Le CSV est produit en mémoire : les limites de volume doivent être évaluées avant une diffusion cible. Il n’existe pas actuellement de téléchargement REST Power BI dans cette application.

## Identifiants et restauration

`scripts.issue_bi_reader` et `scripts.revoke_bi_reader` gèrent les lecteurs techniques. Les jetons sont distincts des secrets S3. Leur audience et namespace doivent rester minimaux. Ne pas exposer les jetons dans la ligne de commande de consommateurs ni dans les journaux.

Après restauration d’une base, des révocations plus récentes peuvent manquer. Réconcilier ou renouveler les accès avant réouverture ; `scripts.revoke_restored_bi_readers` participe à ce contrôle. Une sauvegarde de données ne remplace pas une revue des accès restaurés.

## Validation

`workflow/verify-bi-access.py` réalise un exercice isolé des permissions S3 et de la lecture de versions Delta. Il crée et retire ses ressources de test ; vérifier les cibles avant exécution. Il doit montrer les lectures Gold autorisées et le refus de Bronze, Silver, autres préfixes et écritures.

Les tests `test_bi_reader_service.py` et `test_bi_licenses.py` couvrent les lectures Python, les audiences, révocations, unités et filtres. Ils ne constituent pas une validation de Power BI Desktop, de TLS ou de l’actualisation sur le réseau de l’entreprise.
