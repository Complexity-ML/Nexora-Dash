# Exploitation Nexora-Dash

## Processus indépendants

Dash est servi par Gunicorn depuis `app.main:server`. Les callbacks appellent les services Python et lisent les publications disponibles. Ils ne lancent ni collecte DIGIMON ni Spark. L’image contient les dépendances de traitement pour permettre des processus distincts à partir du même code.

La collecte quotidienne utilise `scripts.collect_daily`. Elle exige `COLLECTION_ENABLED=true` et le contrat de disponibilité `ready_snapshot` du connecteur. Une heure fixe ne suffit pas à prouver que le relevé source est complet. Le service attend une disponibilité explicite et conserve les tentatives dans le journal.

```sh
# Une passe, après configuration du connecteur et du namespace de collecte
python -m scripts.collect_daily --timezone Europe/Paris --once
# Service continu, à superviser indépendamment de Dash
python -m scripts.collect_daily --timezone Europe/Paris
```

Le worker de reprise est disponible dans le profil Compose `recovery`. Il reprend les collectes enregistrées ; il ne remplace pas le collecteur quotidien.

```sh
docker compose --profile recovery up -d recovery-worker
```

Ne pas activer le mode réel tant que le contrat DIGIMON, les identifiants, le périmètre et les permissions n’ont pas été validés. La démonstration locale reste en mode fictif.

Le profil `collection` démarre le collecteur supervisé après configuration et activation de la collecte :

```sh
docker compose --profile collection up -d daily-collector
```

La page Data Lake affiche les journées publiées et distingue le collecteur quotidien du processus de reprise. Elle est réservée aux opérateurs de source. Une nouvelle version de l’interface déclenche une invitation à recharger la page, sans effacer automatiquement les formulaires en cours.

## Publications et supervision

Les lectures d’une collection sont fixées à un manifeste validé. La publication atomique empêche de combiner des tables issues de lots différents. Les lecteurs hors mode collection utilisent la version Gold explicitement résolue.

`python -m scripts.collection_status --help` décrit les bornes de contrôle. Utiliser `--require-daily-worker` et `--require-worker` lorsque ces services doivent être actifs. Le fonctionnement du worker de reprise ne prouve pas celui du collecteur quotidien.

Surveiller les journées attendues et publiées, les rejets, les reprises, les durées et la fraîcheur du Gold. Les journaux doivent contenir des identifiants de lots, jamais des secrets ou des payloads personnels complets.

## Accès

PostgreSQL conserve les utilisateurs, sessions, espaces, rôles, coûts, dossiers et notes. Les services vérifient les accès à chaque commande ou export. Le stockage S3 reste côté serveur.

Gunicorn écoute sur le port 8050. En environnement distant, terminer TLS au reverse proxy, conserver une origine cohérente et activer `DASH_COOKIE_SECURE=true`. Les callbacks refusent les commandes d’une autre origine. La clé de session est persistée dans `dash-session` ; ne pas remplacer ce volume lors d’une simple mise à jour.

Les comptes démo et secrets de développement ne doivent pas servir à un déploiement sur données réelles. Garder PostgreSQL et MinIO hors d’accès du navigateur. Les autorisations S3 BI sont distinctes des espaces applicatifs.

## Sauvegarde, restauration et maintenance

Conserver ensemble les sauvegardes PostgreSQL, objets et références des publications. L’exercice `workflow/verify-collection-restore.py` vérifie une restauration isolée ; consulter son aide et [l’industrialisation](industrialisation.md) avant exécution.

Après restauration, réconcilier les accès techniques et les révocations avant réouverture. Les migrations qui effacent des données ou protègent la traçabilité ne doivent pas annoncer un rollback réussi lorsqu’il serait irréversible.

Compaction et rétention sont des opérations distinctes de la navigation. [Delta Lake](delta-lake.md) décrit les verrous et la protection des références. Ne pas purger des fichiers encore nécessaires à une publication ou sauvegarde. Aucune purge ne découle de l’affichage des pages.

## Limites

La projection de saturation est indicative. Une installation inactive ne prouve pas un droit libérable. Les simulations économiques dépendent des unités, coûts et contrats. La démonstration ne valide ni le réseau cible, ni les données réelles DIGIMON, ni Power BI.
