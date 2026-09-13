# Accès BI au lac Nexora

La préparation de l’accès comporte deux éléments distincts : les identifiants S3
et le connecteur capable de lire une table Delta. Un couple access key / secret key
ne suffit pas, à lui seul, à connecter Power BI Desktop à MinIO.

## Compte S3 dédié

Utiliser un utilisateur MinIO dédié à la BI, sans autre politique attachée. La
politique générée autorise uniquement la lecture des objets et la liste d’un
préfixe Gold explicitement publié pour la BI. Elle ne donne aucun droit d’écriture.
Les espaces applicatifs ne sont pas automatiquement appliqués à cet accès S3 :
chaque audience doit recevoir un préfixe publié correspondant à son périmètre.

```sh
python -m scripts.bi_s3_policy --bucket nexora-lake --prefix demo/gold/bi > /tmp/nexora-bi-policy.json
mc admin policy create local nexora-bi-reader /tmp/nexora-bi-policy.json
mc admin policy attach local nexora-bi-reader --user nexora-bi
```

Le compte `nexora-bi` doit être créé par l’administrateur MinIO avec un secret
aléatoire conservé dans le gestionnaire de secrets. L’alias `local` est un alias
administrateur configuré localement ; aucun identifiant administrateur ne doit
être utilisé dans Power BI. Utiliser HTTPS sur un réseau distant.

Le script prépare la politique ; il ne crée pas de compte, ne publie pas de
nouvelles tables et n’active pas une connexion Power BI.

## Lecture des tables

Une table Delta se lit à partir de son journal transactionnel. Charger tous les
fichiers Parquet du dossier inclurait potentiellement des versions obsolètes.
Pour Power BI, prévoir un service **Delta Sharing** exposant uniquement les tables
Gold autorisées, ou un moteur SQL compatible Delta relié au stockage S3.
Le service lecteur utilise le compte S3 dédié ; Power BI utilise l’authentification
du service choisi. Le connecteur et l’actualisation doivent être validés avec
l’environnement Power BI de l’entreprise avant de présenter l’intégration comme
opérationnelle.

Le préfixe Gold BI doit contenir les tables publiées et leur journal Delta, sans
référence nécessaire à Bronze ou Silver. Les manifestes internes Nexora ne sont
pas un catalogue BI public.

## Vérification avant activation

Avec le compte dédié, vérifier une lecture Gold autorisée, puis le refus d’une
lecture Bronze/Silver, d’une liste hors préfixe et d’une écriture. Vérifier ensuite
la lecture d’une version Delta cohérente et une actualisation Power BI réelle.

Références : [connecteur Delta Sharing Microsoft](https://learn.microsoft.com/en-us/power-query/connectors/delta-sharing)
et [politiques MinIO](https://github.com/minio/minio/blob/master/docs/multi-user/README.md).

## Test local reproductible des permissions

Depuis la racine du dépôt :

```sh
python3 workflow/verify-bi-access.py --docker /chemin/vers/docker
```

L’exercice crée un bucket, une politique et un utilisateur MinIO temporaires.
Le secret aléatoire passe par l’entrée standard, sans être enregistré dans le
rapport. Le compte limité est testé avec le client S3 : lecture et liste du
préfixe Gold autorisées ; lectures Bronze, Silver et autre Gold, listes hors
préfixe, écriture et suppression refusées avec `AccessDenied`.
Le compte, la politique et le bucket de test sont retirés en fin d’exercice.
Aucun droit n’est ajouté aux comptes existants et le bucket de démonstration
n’est pas modifié.

L’exercice crée également une table Delta Gold synthétique, puis remplace son
contenu. Avec les seuls identifiants du lecteur BI, il vérifie la lecture de la
version 0 (valeur 10) et de la version courante 1 (valeur 20). Le lecteur utilise
le journal Delta et ne mélange pas les deux versions des fichiers Parquet.

Cet exercice a été exécuté avec succès sur MinIO local, permissions et lecture
Delta comprises. Il ne valide pas encore le service de connexion BI, TLS sur le
réseau cible ou une actualisation dans Power BI.

## Instantané Gold dédié aux usages de pools

`app.bi.snapshot.export_pool_snapshot` prépare un instantané autonome sous
`gold/bi/<audience>/<identifiant>/`. L’opérateur fournit explicitement les pools
autorisés pour cette audience ; une sélection vide ou contenant un pool absent
est refusée. Cela ne remplace pas une politique d’autorisation de l’entreprise.

La table `pool_usage` contient la journée, l’identifiant et le nom du logiciel,
l’identifiant du pool, sa capacité et les quantités utilisées/disponibles. Elle
ne contient ni utilisateurs ni machines et ne représente pas les installations,
les droits contractuels ou les économies du parc entier. Le manifeste conserve
l’identifiant du lot source et l’empreinte de son manifeste pour la traçabilité.
Toutes ses dépendances de lecture sont dans le préfixe Gold BI ; aucun accès à
Bronze ou Silver n’est nécessaire au lecteur de cet instantané.

La table et le manifeste sont relus après écriture. Chaque appel crée une
candidate distincte ; il ne change aucun pointeur BI et n’accorde aucun accès.
Un service de diffusion doit sélectionner un seul instantané validé, plutôt que
concaténer les répertoires des exports successifs. L’export travaille en mémoire ;
son dimensionnement et sa publication dans le service Power BI restent à réaliser.
Les exports d’inventaire, de droits et de coûts ne sont pas encore couverts.

## Catalogue interne de publication

`prepare_pool_snapshot` enregistre une candidate vérifiée et sa provenance dans
PostgreSQL. `publish_snapshot` sélectionne une candidate pour une audience en
comparant le pointeur BI attendu et la publication source exacte sous verrou.
Une candidate devenue ancienne est refusée ; une autre publication BI ne peut
pas être écrasée à partir d’une ancienne référence. La répétition d’une adoption
identique est sans effet. Le lecteur interne récupère pointeur et artefact dans
une seule requête, sans parcourir tous les exports.

Les candidates, y compris non publiées, alimentent l’inventaire des dépendances
à sauvegarder. La migration conserve cette traçabilité et refuse son rollback.
Ce catalogue n’est pas un endpoint public et ne donne pas d’autorisation S3 :
le service de diffusion devra authentifier son lecteur et vérifier son audience.

## Restauration du catalogue BI

L’exercice `workflow/verify-collection-restore.py` prépare un instantané BI publié
et une seconde candidate, puis gèle PostgreSQL et les références à sauvegarder.
Il publie ensuite une autre journée et un nouvel instantané BI dans la source.
Après suppression de la base et du lac sources de test, la restauration retrouve
uniquement les deux instantanés antérieurs au gel, le bon pointeur d’audience et
la table Gold lisible. L’exécution locale a vérifié 30 fichiers et la reprise du
lot interrompu avec 24 relevés. Le test de migration vérifie également qu’un
rollback interdit conserve la révision PostgreSQL actuelle.

## Identité technique du lecteur

Le module interne `app.bi.auth` prépare des jetons aléatoires de lecture, distincts
des comptes SAM et des identifiants S3. Seul leur hash est stocké ; le jeton clair
est retourné une fois au provisionneur autorisé, pour le gestionnaire de secrets.
Chaque identité est liée à un namespace et une audience, expire (24 heures par
défaut, 90 jours au maximum) et peut être révoquée. La lecture du catalogue déduit
l’audience du jeton, sans accepter une audience arbitraire fournie par le lecteur.

Il n’existe pas d’endpoint public de création de jetons. Ce composant ne configure
pas encore le connecteur Power BI et ne remplace pas les permissions du compte
S3 utilisé par le service. La diffusion devra utiliser TLS et gérer la rotation.
Après restauration d’une ancienne base, des révocations postérieures au point de
sauvegarde ne sont plus présentes : les accès doivent être réconciliés ou renouvelés
avant réouverture du service. La migration interdit un rollback silencieux de cette
traçabilité.

## Route de lecture du catalogue

`GET /api/bi/publication` est désactivée par défaut (`BI_ENABLED=false`). Lorsqu’elle
est activée, `BI_NAMESPACE` fixe côté serveur le namespace desservi et l’en-tête
`Authorization: Bearer …` identifie le lecteur technique. L’audience vient du jeton,
jamais d’un paramètre de requête. La réponse contient l’identifiant de l’instantané
publié et son artefact (clé Gold, empreinte), avec `Cache-Control: no-store`.
Les jetons absents, invalides ou révoqués donnent 401 ; une audience sans publication
donne 404. Une indisponibilité du catalogue donne 503 sans exposer l’exception.

La route n’interroge pas DIGIMON et ne donne aucun identifiant S3.

## Téléchargement des observations de pools

`GET /api/bi/pool-usage.csv?snapshot_id=…` utilise le même jeton et le même
namespace. Le lecteur transmet l’identifiant obtenu dans le catalogue. Si une
nouvelle publication l’a remplacé avant la résolution du téléchargement, la route
répond 409 : relire le catalogue puis relancer le téléchargement. Une publication
qui change après cette résolution ne modifie pas la version Delta épinglée lue.

Le service vérifie l’empreinte du manifeste, son audience, le chemin de la table
sous le même instantané Gold BI, le schéma et le nombre de lignes. La lecture est
protégée par le verrou partagé de maintenance. Un artefact invalide produit une
réponse 503 sans détail interne. Les réponses ne sont pas mises en cache.

Cette première lecture CSV charge la table en mémoire et concerne uniquement les
observations des pools sélectionnés. Elle ne convient pas encore à un export
massif de l’inventaire. Les installations, droits et coûts restent à exposer par
des publications adaptées. Ce service REST n’implémente pas Delta Sharing.
L’activation dans la stack, TLS, la rotation des jetons et une actualisation réelle
avec Power BI restent à valider ; BI reste désactivé dans la démonstration.

Les tests de téléchargement écrivent une nouvelle version de la table après
publication et vérifient que le CSV conserve les valeurs de la version publiée.
Ils rejettent aussi une audience ou un chemin de table incorrects, une version
Delta invalide et un nombre de lignes incohérent, même si l’empreinte du manifeste
a été recalculée. Ces contrôles complètent les essais HTTP de révocation et de
changement de publication ; ils ne constituent pas une validation Power BI.

## Réouverture après restauration

Maintenir le service BI et le provisionnement de lecteurs arrêtés. Dans la base
restaurée, `python -m scripts.revoke_restored_bi_readers --namespace <namespace>`
compte les identités encore non révoquées sans les modifier. Ajouter `--apply`
révoque ces identités dans ce seul namespace. Réexécuter est sans effet sur les
identités déjà révoquées. Le verrou de table sérialise l’opération avec les
émissions en cours ; il ne remplace pas l’arrêt du provisionnement.

Après ce traitement, créer de nouveaux jetons, les diffuser via le gestionnaire
de secrets, puis rouvrir BI. Les autres namespaces restent inchangés ; traiter
explicitement chacun de ceux restaurés avant d’en rouvrir l’accès. La commande ne
coupe pas les requêtes déjà en cours, d’où l’arrêt préalable du service.

L’exercice de restauration inclut un jeton révoqué après le point sauvegardé :
il vérifie sa validité dans l’ancienne base restaurée puis son refus après la
réconciliation. Aucun jeton de démonstration existant n’est modifié par cet essai,
qui utilise des bases temporaires.

Pour un lac sans préfixe, le namespace est la chaîne vide (`BI_NAMESPACE=""`).
Les fonctions internes d’émission acceptent ce namespace explicite. Le CLI de
réconciliation utilise `--root` à la place de `--namespace` : il cible uniquement
ce namespace racine, jamais tous les préfixes du bucket. Sans `--apply`, il reste
en prévisualisation. Les tests vérifient qu’un jeton racine n’accède pas à un
namespace de démonstration et que sa révocation laisse ce dernier intact.

## Volumes d’inventaire par implantation

`prepare_inventory_snapshot` prépare une publication distincte à partir de l’index
référencé par le manifeste publié. L’opérateur fournit les identifiants explicites
des filiales autorisées pour l’audience ; une filiale inconnue fait échouer l’export.
PostgreSQL agrège les machines par filiale, site, système, type et environnement.
Seuls ces groupes passent en mémoire puis dans la table Delta `inventory_counts`.
Les sites sélectionnés sans machine produisent un compte nul. Aucun identifiant
de machine, utilisateur, adresse e-mail ou relation individuelle n’est exporté.

Le manifeste conserve l’empreinte de sa source et la version Delta. La publication
utilise le même contrôle de concurrence que les pools. Ces volumes décrivent le
parc au relevé de l’index, pas un nombre de licences ni un historique d’usage.
`GET /api/bi/inventory-counts.csv?snapshot_id=…` télécharge cette table avec le
jeton de l’audience et l’identifiant du catalogue. Le service vérifie le type de
contenu, le schéma et la version publiée. Demander les pools à une publication
d’inventaire retourne 404, sans substituer des données d’un autre périmètre.
Le fichier contient des groupes agrégés ; le téléchargement les charge en mémoire.
L’actualisation réelle dans Power BI reste à valider.

### Mesure locale de l’agrégation

`python -m scripts.benchmark_bi_inventory --repeats 8 --concurrency 4` effectue
uniquement des transactions en lecture seule sur l’index actif de la source mock,
avec un délai SQL limité. Chaque lecture compare la somme agrégée au nombre de
machines sélectionnées dans l’index. Le benchmark ne prépare ni ne publie de BI.

Sur la démonstration : 138 500 machines, 12 filiales, 1 286 groupes exportables.
Huit lectures avec concurrence 4 ont donné une médiane de 252 ms et un maximum
(p95 sur ce petit échantillon) de 255,5 ms. La requête initiale prenait 11,6 secondes
sur une lecture et échouait au benchmark concurrent. L’agrégation préalable des
machines, avant jointure avec les sites, conserve les mêmes totaux et évite ce coût.
Ces mesures concernent PostgreSQL local et ses caches, pas un transfert CSV, la
publication Delta, des utilisateurs Power BI ni le réseau Safran.

## Licences par produit et filiale

`prepare_license_snapshot` prend une sélection explicite d’identifiants de produits
et de filiales. Il lit seulement les dimensions produits, filiales et licences du
dernier relevé publié, sans charger les machines. La table conserve chaque licence
source, sa quantité, son unité, la devise, le coût unitaire annuel fourni et le
marqueur fictif. Les quantités absentes restent nulles et les unités différentes ne
sont pas additionnées. Les noms identiques ne fusionnent pas les identités produit.

Les licences sans filiale ne sont pas réparties automatiquement. Par défaut,
elles sont exclues et leur nombre est conservé dans `excluded_global_entitlements`.
L’opérateur peut autoriser leur inclusion avec `include_global=True` : elles restent
sans filiale dans le CSV, sans duplication entre implantations. Une liste de filiales
vide avec cette option sélectionne uniquement les licences globales des produits
choisis. Le manifeste conserve `includes_global_entitlements` ; l’option exige un
booléen explicite et n’est pas commandée par le lecteur HTTP. Un export
vide ne prouve pas une absence de droits. Les coûts ne constituent pas des économies.

`GET /api/bi/license-entitlements.csv?snapshot_id=…` utilise le jeton de l’audience
et les mêmes contrôles de publication que les autres tables. Le fichier est lu en
mémoire ; les limites de diffusion et la validation Power BI restent applicables.

## Description de la publication

`GET /api/bi/description?snapshot_id=…` expose les métadonnées vérifiées du
manifeste : contenu, schéma attendu, versions Delta, nombre de lignes, sélection
et éventuelles exclusions. Le jeton et l’identifiant de publication sont contrôlés
comme pour le CSV. La réponse ne diffuse pas les chemins de stockage.

Cette lecture légère décrit le contrat du manifeste sans relire les lignes ; le
CSV contrôle ensuite le schéma physique et le nombre de lignes. Elle permet au
lecteur de distinguer une sélection de filiales, une inclusion de licences globales
et une publication de pools, avant d’utiliser les chiffres. Les champs absents ne
sont pas remplacés par des hypothèses de couverture.

L’exercice de restauration couvre les publications de pools, d’inventaire et de
licences, ainsi qu’un candidat non publié : quatre instantanés BI, 40 fichiers
vérifiés. Après suppression des sources temporaires, il relit les CSV d’inventaire
et de licences depuis les versions restaurées, compare le nombre de machines à la
fixture et vérifie quantité et unité de la licence. Ces fixtures restent fictives
et ne remplacent pas une actualisation Power BI sur le réseau cible.

Chaque réponse CSV réussie contient `X-Nexora-Snapshot-ID` et
`X-Nexora-Content-SHA256`, calculé sur les octets UTF-8 effectivement envoyés.
Le consommateur peut conserver ces en-têtes avec le fichier pour identifier la
publication et vérifier son intégrité ultérieure. Cette empreinte ne constitue
pas une signature ; elle ne remplace pas HTTPS ni l’authentification.

## Remise d’un accès technique

Depuis l’environnement opérateur du backend, créer un fichier nouveau dans un
répertoire privé, hors Git :

```sh
python -m scripts.issue_bi_reader --namespace demo-generations/IDENTIFIANT/ \
  --audience finance --lifetime-hours 24 --output /chemin/prive/finance.json
```

`--root` sélectionne explicitement la racine à la place de `--namespace`.
Le fichier contient le secret et porte les permissions `0600`. Un fichier existant
ou un lien symbolique est refusé avant toute émission. La sortie standard ne
contient que l’identifiant et l’expiration ; transférer le fichier vers le
 gestionnaire de secrets par un canal autorisé. Cette commande n’active pas BI.

Le fichier et son répertoire sont synchronisés avant le commit PostgreSQL qui
active le lecteur. Une erreur de remise annule la transaction : aucun lecteur
n’est créé. Un arrêt avant commit peut laisser un fichier contenant un jeton
invalide ; un résultat de commit incertain demande de vérifier l’identifiant avant
réessai. La durabilité dépend des garanties `fsync` du système de fichiers choisi.
Le fichier réservé reste en place pour inspection, sans écrasement automatique.

Pour retirer un lecteur précis, utiliser son identifiant public, jamais son jeton :

```sh
python -m scripts.revoke_bi_reader --namespace demo-generations/IDENTIFIANT/ \
  --reader-id UUID_DU_LECTEUR
```

La commande ne touche pas les autres lecteurs, même de la même audience. Une
révocation répétée réussit ; un identifiant absent du namespace indiqué retourne
`not_found` avec un code de sortie non nul. Pour une rotation, remettre le nouveau
secret au consommateur, vérifier son accès puis révoquer l’ancien identifiant.
La révocation s’applique aux prochaines authentifications ; elle n’interrompt pas
une réponse déjà autorisée et en cours de téléchargement.

Un test lance le provisionnement dans un processus distinct, attend la
synchronisation du fichier et du répertoire puis envoie `SIGKILL` avant le commit.
Il vérifie que le jeton écrit ne permet aucun accès, qu’aucun lecteur n’est publié
en base et qu’une nouvelle émission réussit. Cela couvre une interruption de
processus ; pas une panne électrique ni les garanties d’un stockage distant.
