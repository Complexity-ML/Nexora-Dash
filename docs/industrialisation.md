# Industrialisation et reprise par métadonnées

## Objectif

Faire évoluer le lac de démonstration vers une collecte DIGIMON exploitable,
avec publication contrôlée, reprise après panne et résultats traçables.
Les validations nécessitant l’API réelle, le réseau Safran ou Power BI restent
explicitement ouvertes tant que ces environnements ne sont pas disponibles.

## État constaté

- MinIO conserve les données ; Silver et Gold utilisent des versions Delta.
- Les manifestes d’inventaire référencent les versions de tables et le pointeur
  actif est géré dans PostgreSQL. Certaines publications comparent le run et le
  manifeste sous verrou avant activation.
- Les migrations Delta disposent de mécanismes de reprise spécifiques.
- La collecte `SamPipeline.persist_snapshot` écrit successivement Bronze, usages
  Silver et inventaire Silver. Ces opérations ne constituent pas une transaction
  commune. La validation du payload précède actuellement son archivage Bronze.
- Le mode optionnel de collecte journalisée dispose de checkpoints Bronze,
  validation, Silver et Gold, de baux renouvelés et d’une publication atomique
  dans PostgreSQL. Les tests couvrent les interruptions et les corrections.
  La boucle quotidienne et le rattrapage historique sont testés comme composants.
  Leur adaptateur et leur service, ainsi que le basculement de la démonstration
  d’entreprise, restent à terminer ; le chemin historique existe encore.
- La reprise périodique dispose d’un profil Docker opt-in, de délais progressifs,
  d’un arrêt par signal et d’une supervision persistée. Son cycle a été testé
  dans un conteneur isolé ; il reste désactivé dans la démonstration historique.
- La restauration PostgreSQL + Delta a été testée avec un instantané exporté,
  des écritures ultérieures et la reprise d’un lot interrompu sans source.
  La sauvegarde à chaud généralisée et la purge coordonnée restent à terminer.
- Le lecteur BI limité a été testé contre MinIO : lecture de deux versions Delta
  Gold et refus des accès hors périmètre, de l’écriture et de la suppression.
  Le service de connexion et l’actualisation Power BI restent à valider.
- Le catalogue indexé a été mesuré sur 138 500 machines avec quatre lectures
  concurrentes. Ce contrôle local ne valide pas la charge ni le réseau Safran.

## Métadonnées utiles

Chaque collecte doit enregistrer :

| Champ | Rôle |
| --- | --- |
| Source, périmètre, identifiant de relevé et révision | Identifier précisément ce qui est collecté |
| Empreinte SHA-256 et objet Bronze | Vérifier le contenu et permettre son rejeu |
| Date métier, date de réception, disponibilité source | Distinguer retard de collecte et absence de données |
| Version du schéma et du mapping | Reproduire la transformation |
| Tentative, propriétaire du traitement, bail et jeton de verrouillage | Empêcher un ancien worker de publier après reprise |
| État de chaque étape et erreur structurée | Reprendre au dernier point validé |
| Tables, versions Delta et compteurs | Identifier exactement les sorties produites |
| Résultats qualité et couverture par filiale/produit | Décider si une publication est complète ou partielle |
| Manifeste précédent et manifeste publié | Revenir à une génération validée et tracer les corrections |

Ne pas conserver de secrets dans ces métadonnées. Une erreur doit être nettoyée
avant journalisation pour ne pas exposer de payload ou d’identifiant sensible.

## Protocole cible

1. **Réception** : archiver la réponse source immuable et son empreinte. Un payload
   invalide doit pouvoir être conservé en quarantaine selon la politique de
   données, avec un motif de rejet, sans être promu en Silver.
2. **Validation** : vérifier schéma, clés, relations, unités, disponibilité et
   complétude attendue. Le dénominateur attendu vient du contrat source ; il ne
   doit pas être déduit uniquement des lignes reçues.
3. **Transformation** : produire des versions Silver identifiées par le run.
   Enregistrer les références seulement après vérification de leur lisibilité.
4. **Analyse** : calculer Gold sur ces références précises, pas sur des tables
   « latest » susceptibles de changer pendant le calcul.
5. **Publication** : vérifier les contrôles, le bail et le manifeste précédent,
   puis basculer un unique pointeur actif atomiquement. Les lecteurs doivent
   tous suivre ce protocole avant de revendiquer une publication globale atomique.
6. **Reprise** : réutiliser les sorties vérifiées ; rejouer uniquement les étapes
   manquantes ou invalidées. Une nouvelle révision source est une correction,
   pas une répétition à ignorer.

Une panne après un commit Delta mais avant l’enregistrement du point de reprise
exige de retrouver le commit par un identifiant d’opération durable. Ce cas doit
être testé ; une simple relance aveugle ne suffit pas.

## Trois formes de reprise

- **Reprise de traitement** : continuer un run interrompu à partir de ses étapes
  vérifiées, sans dupliquer les données métier.
- **Retour à une publication précédente** : repointer vers un manifeste dont
  toutes les versions sont encore lisibles. Les coûts et dossiers métier ne
  sont pas automatiquement restaurés avec les données analytiques.
- **Restauration après perte du stockage** : restaurer PostgreSQL, objets sources,
  manifestes, journaux Delta et fichiers référencés depuis une sauvegarde cohérente.
  Les seules métadonnées ne recréent pas des fichiers perdus. Le rejeu Bronze est
  une alternative si la source archivée et la version des transformations restent
  disponibles.

## Livraisons et preuves attendues

| Lot | Travail | Preuve de fin |
| --- | --- | --- |
| 1. Journal et reprise | Modèle persistant, transitions, idempotence, bail, publication partagée | Tests de panne avant/après chaque commit, reprise et concurrence |
| 2. Collecte automatique | Ordonnanceur batch, disponibilité, pagination, tentatives, corrections | Plusieurs journées simulées, retard, panne et rattrapage |
| 3. Qualité et catalogue | Contrats, rejets, couverture, lignage et alertes | Une filiale absente et un schéma incompatible sont détectés sans zéro artificiel |
| 4. Exploitation | Sauvegarde, restauration, supervision, compaction et rétention | Restauration isolée vérifiée ; versions encore référencées protégées contre la purge |
| 5. Accès et BI | Identités techniques, périmètres Gold, service compatible Delta | Lecture autorisée et refus hors périmètre ; actualisation Power BI réelle |
| 6. Charge et intégration | Profilage, API DIGIMON réelle, réseau et concurrence | Mesures reproductibles à froid et à chaud, reprise validée sur le contrat réel |

Les lots 1 à 4 peuvent avancer sur une source fictive contrôlée. La connexion BI,
les règles réelles d’authentification et la validation finale DIGIMON nécessitent
les environnements correspondants. Aucun résultat de démonstration ne vaut preuve
sur le réseau de production.

## Garde-fous de rétention

La maintenance doit connaître les versions actives, les versions de retour arrière
conservées et les traitements en cours. La purge et la publication doivent partager
un mécanisme d’exclusion ou de réservation pour éviter une course entre vérification
et suppression. Une sauvegarde du seul journal PostgreSQL ou du seul `_delta_log`
ne constitue pas une sauvegarde restaurable du lac.

## Premier lot implémenté : journal PostgreSQL

La migration `0010_collection_journal` et `app/collection/journal.py` ajoutent
l’identité des runs, les empreintes, les versions de mapping/schéma, les points de
reprise immuables, les baux renouvelables et le jeton qui invalide un ancien worker.
La publication du pointeur et le passage du run à `published` partagent une
transaction PostgreSQL avec comparaison de la publication précédente.

Les tests PostgreSQL vérifient l’identité/révision source, les étapes conservées
lors d’une reprise, deux claims concurrents, le refus d’un ancien worker, les
échecs rejouables ou définitifs, l’ordre des étapes et un pointeur périmé.

Le journal est raccordé à la synchronisation et aux lecteurs applicatifs lorsque
`COLLECTION_ENABLED=true` ; ce mode reste désactivé par défaut. Les vérifications des
artefacts et les écritures isolées sont assurées par ce parcours. Le journal clôture les écritures de métadonnées
et la publication ; il n’empêche pas à lui seul un ancien worker d’écrire dans S3.
Les lecteurs de ce mode utilisent le manifeste référencé par le pointeur commun.

## Place éventuelle de GraphQL

GraphQL est une option pour composer les réponses destinées aux écrans Nexora :
produits, licences, filiales et indicateurs. Il ne remplace ni Delta, ni le journal
de collecte, ni le protocole de reprise. Le contrat REST DIGIMON reste indépendant.

Avant de l’ajouter, mesurer les besoins de composition réels. Toute introduction
devra conserver les contrôles de périmètre, borner la pagination et la complexité
des requêtes, et éviter les lectures répétées de machines ou de tables Delta dans
les résolveurs. Le choix REST/GraphQL ne dispense pas d’optimiser les accès aux données.

## Raccordement expérimental au pipeline

`SamPipeline.collect_recoverable(raw, journal, ...)` exécute maintenant le parcours
Bronze → validation → Silver Delta → calcul Gold → publication dans
`collection_heads`. L’identité inclut les réglages analytiques pour ne pas
réutiliser silencieusement un calcul produit avec d’autres seuils.

Chaque tentative écrit sous son propre préfixe. Un ancien worker peut terminer
une écriture isolée, mais son jeton expiré l’empêche de publier. Une panne après
un commit Delta et avant son checkpoint peut laisser des fichiers orphelins : la
reprise produit une autre tentative sans dupliquer les lignes du jeu publié.
Ces orphelins devront être traités par la maintenance, après vérification des
références et des traitements actifs.

Le manifeste décrit l’historique par journée. Une correction explicite remplace
la référence de sa journée et conserve celles des autres jours. Les versions
Silver récupérées sont comparées au contenu source validé. Les références Gold
et les dépendances historiques sont vérifiées avant publication. Les données
invalides restent archivées en Bronze sans publication.

Les tests injectent des interruptions après chaque écriture et chaque checkpoint,
avant et après publication. Ils couvrent aussi le remplacement d’un worker expiré,
la correction d’une journée, une répétition après publication, un vrai calcul
Spark et une reprise sur MinIO dans un préfixe isolé.

Le parcours est activable explicitement selon la procédure ci-dessous.
L’import initial de la génération existante et sa bascule restent à vérifier.

Les collectes d’un même triplet namespace/source/périmètre sont maintenant
sérialisées par un bail acquis sous verrou transactionnel. Un heartbeat renouvelle
ce bail pendant les calculs et les accès au stockage. Un échec de renouvellement
empêche la publication ; le délai doit rester adapté à l’infrastructure.

Si la publication de référence a changé avant une reprise, `reconcile` archive
les anciens checkpoints dérivés dans `collection_step_history`, conserve Bronze
et recommence la validation et les transformations sur la publication actuelle.
Le test de reprise conserve ainsi une journée arrivée pendant l’interruption.
L’ordonnancement des révisions source opaques reste à définir avec DIGIMON : cette
réconciliation ne déduit pas qu’une révision reçue tardivement est plus récente.

`PublishedCollection` fixe un manifeste publié à sa construction, contrôle son
empreinte et son périmètre, puis lit uniquement les versions Delta référencées.
Une nouvelle publication ne change pas les données d’un lecteur déjà ouvert.
Une journée sans inventaire ne présente pas un ancien inventaire comme actuel.
Cet adaptateur est utilisé par les endpoints lorsque le mode de collecte avec reprise est activé.

## Activation applicative contrôlée

`COLLECTION_ENABLED=true` raccorde désormais les endpoints d’analyse, historique,
stock et usage courant à une publication du journal. `COLLECTION_SOURCE` et
`COLLECTION_SCOPE` identifient le flux ; en démonstration, la source reste
`digimon-mock`. Le comportement antérieur reste actif par défaut.

L’index d’inventaire est préparé dans un espace isolé avant publication. Le
manifeste fixe son identifiant de run, et les routes d’inventaire et de licences
utilisent cette version précise, même si un autre index est préparé. Les petites
dimensions produits, licences et filiales sont également conservées dans Delta.

La synchronisation exécute le traitement hors de la boucle HTTP. Les appels
répétés du même relevé renvoient la même identité de collecte. Pour une source
réelle, les champs `snapshotId` et `sourceRevision` doivent être adaptés au contrat
DIGIMON ; aucune identité de révision n’est inventée automatiquement. La démo peut
utiliser la date source et l’empreinte du JSON canonique comme identité fictive.

L’activation est refusée avec une erreur 503 si un historique antérieur ou un
index existe sans publication importée. Il reste à fournir et vérifier l’import
initial de la génération existante avant d’activer ce mode sur la démonstration
courante. Les tests activent ce parcours dans des espaces isolés uniquement.

### Import de l’historique existant dans le journal

`nexora lake import` (depuis `nexora/`) prépare une publication à partir des
versions Delta et de l’index existants. Il ne copie pas les observations et ne change
aucun pointeur actif pendant cette préparation. Le dernier stock doit correspondre
à un relevé Bronze archivé ; les quantités ne sont pas déduites des installations.

Les contrôles couvrent les comptages des dimensions, chaque partition des historiques
`daily` et `product_usage_daily`, les dates dupliquées et les dépendances du rapport
d’usage des installations. Ils vérifient les références et comptages, pas l’exactitude
métier de chaque observation. Le manifeste d’inventaire est copié sous une clé propre
à la publication pour éviter qu’une modification ultérieure de l’index change sa lecture.

L’activation est distincte (`--activate-artifact <fichier-json> --writers-stopped`).
Les collecteurs historiques doivent être arrêtés : ils ne participent pas aux verrous
du journal. Toute modification des références source après préparation bloque cette
activation. Les tables référencées doivent être conservées par la politique de rétention.

Le mode de collecte journalisé reste optionnel. Avant de l’activer sur la démonstration
d’entreprise, la collecte suivante doit préserver sa couverture d’inventaire et son
historique d’usage ; le petit connecteur fictif ne peut pas remplacer cet inventaire.

Une correction portant sur une journée antérieure au dernier relevé conserve
l’index d’inventaire importé et son manifeste. Elle ne remplace pas l’inventaire
courant par celui de la journée corrigée.

### Contrôle de baisse de couverture

Chaque publication journalisée conserve un profil de couverture : machines et
utilisateurs par filiale, installations par identifiant produit, et présence de
licences renseignées par produit, filiale et unité. Les quantités de licences ne
sont jamais additionnées entre unités différentes pour ce contrôle.

`COLLECTION_MINIMUM_RETAINED_FRACTION` fixe la fraction minimale conservée par
rapport à la référence publiée (0,9 par défaut). Une baisse supérieure bloque
la publication avec `COVERAGE_DECREASE`. Le checkpoint de validation contient
les dimensions concernées, les compteurs antérieurs et les compteurs reçus ;
Bronze reste disponible pour diagnostic. Ce seuil est un garde-fou opérationnel,
pas une affirmation de complétude de la source. La première collecte n’a pas de
référence : le rapport l’indique explicitement. Une réduction légitime du parc
nécessite de revoir la politique ou le contrat de périmètre ; elle ne doit pas
être acceptée en relançant aveuglément le même relevé rejeté.

La politique entre dans l’identité de transformation pour permettre une nouvelle
évaluation explicite après changement de configuration. Une correction historique
est comparée au profil de la même journée lorsqu’il existe, plutôt qu’au parc
actuel. Le contrôle ne remplace pas les attendus de complétude fournis par DIGIMON,
qui restent à définir avec son contrat réel.

### Reprise sans disponibilité de DIGIMON

`nexora collect recover --limit 10` exécute une passe bornée sur
les runs rejouables et les baux expirés du seul périmètre configuré. La commande
nécessite le mode journalisé. Elle ne contacte pas la source : le payload Bronze,
son empreinte et les versions de transformation permettent de reprendre le même
run. Les runs rejetés par la qualité et les imports en attente d’activation ne
sont pas relancés automatiquement.

Le résultat JSON distingue publication, concurrence, configuration modifiée,
source à récupérer, métadonnées de rejeu absentes et échec. Les exceptions brutes
ne sont pas exportées. Une configuration modifiée ne doit pas produire une
nouvelle transformation sous l’identité de l’ancienne tentative. Les anciens
payloads sans métadonnées de rejeu sont signalés, sans deviner leur mapping.

Cette commande constitue une passe de reprise utilisable par un ordonnanceur.
Elle ne constitue pas encore la collecte quotidienne : le contrôle de disponibilité
DIGIMON, la récupération des pages et le rattrapage de journées restent à raccorder
au contrat source. Aucun ordonnanceur n’est activé sur la démonstration à ce stade.

### Diagnostic des journées et des traitements

`nexora collect status --from AAAA-MM-JJ --through AAAA-MM-JJ`
compare une fenêtre attendue explicite aux journées du manifeste publié. La borne
finale doit correspondre à une journée dont les données devraient déjà être
disponibles selon le contrat source ; la commande ne devine pas cette échéance.
Elle ne remplace jamais une journée absente par un usage nul.

Le JSON contient les journées absentes, les états des runs, les baux expirés et
les rejets de qualité (dimensions et compteurs). Les détails sont limités à 100
incidents, avec compteur total et indicateur de troncature. Les payloads, secrets
et exceptions brutes ne sont pas exposés. La commande retourne 1 lorsqu’une
journée attendue manque ou qu’un incident figure au journal, sinon 0. Les anciens
rejets restent visibles : leur résolution ou acquittement n’est pas encore géré.
Ce diagnostic porte sur les publications journalisées, pas sur une génération
historique qui n’a pas encore été importée.

### Traitement batch des journées disponibles

`app.collection.daily.collect_days` traite une fenêtre explicite de 366 jours au
maximum. Son adaptateur `DailySource` fournit soit `None` (source indisponible),
soit un `ReadySnapshot` complet avec journée métier, identifiant et révision source.
Une date de capture seule ne prouve pas que le relevé est complet. Ce contrat
interne doit être implémenté par le raccordement DIGIMON réel, pas supposé à partir
d’un champ de son API actuelle.

Une nouvelle passe interroge aussi les journées déjà publiées pour détecter les
corrections. Le journal rend la répétition d’une même révision idempotente. Les
journées retardées restent absentes jusqu’à leur disponibilité ; un échec ne
bloque pas le traitement des autres journées. La journée attendue fait partie de
l’identité de transformation et des métadonnées de rejeu. Le payload est archivé
avant vérification de sa date métier.

Les tests simulent trois journées, un retard, une correction, une répétition et
un payload portant une mauvaise date. La section « Boucle de collecte quotidienne »
décrit son orchestration périodique testée. L’adaptateur DIGIMON et le service de
collecte ne sont pas encore activés.

### Protection contre l’ancien nettoyage

Le script `cleanup_migrated_demo` refuse désormais toute suppression si la base
contient un run de collecte, même non publié. Son verrou de table est conservé
jusqu’à la fin de la transaction de nettoyage et empêche l’inscription concurrente
du premier run. Sans les tables de reprise migrées, il refuse également d’agir.
Ce script historique ne sait pas calculer les dépendances du journal.

`app.collection.dependencies.dependency_inventory` parcourt les références de
manifestes, leurs prédécesseurs et les versions Delta épinglées. Une dépendance
JSON manquante interrompt le parcours. Les cycles ne provoquent pas de boucle.
Ce module inventorie les références pour la future maintenance ; il ne purge
aucun objet et ne remplace pas la vérification des fichiers physiques Delta.
La politique de conservation, les réservations des traitements en cours et
l’exclusion entre publication et purge restent nécessaires avant tout `VACUUM`.

### Fichiers nécessaires à une restauration Delta

`delta_backup_files` ouvre chaque version épinglée via le journal Delta et
énumère ses fichiers de données. Il ajoute les journaux et checkpoints jusqu’à
la plus haute version conservée. Le pointeur `_last_checkpoint` est exclu : il
pourrait désigner une version plus récente qui n’appartient pas à la sauvegarde.
Les chemins extérieurs à la table sont refusés.

Le test restaure deux versions dans un répertoire isolé, supprime la source de
test et vérifie les données des deux versions ainsi que la version maximale
restaurée. Cela valide le composant de restauration Delta sur les tables du
prototype. Ce n’est pas encore une sauvegarde complète du service : il faut aussi
capturer PostgreSQL, les manifestes et Bronze, vérifier les empreintes des copies,
coordonner la rétention et tester la restauration de l’ensemble. L’inventaire de
fichiers ne copie ni ne supprime les données du lac.

### Vérification croisée PostgreSQL et lac

Depuis la racine, `python3 workflow/verify-collection-restore.py` utilise la stack
Docker locale pour créer deux bases PostgreSQL temporaires et un lac de test.
L’option `--docker` permet d’indiquer le chemin de l’exécutable Docker.

La fixture publie un relevé avec Spark, crée des comptes fictifs, des membres et
un coût. Elle maintient un instantané PostgreSQL exporté dans une transaction
en lecture seule et y lit les références des checkpoints, archives et publications
du namespace. Elle modifie ensuite le coût et publie une troisième journée avec
Spark, puis copie les fichiers désignés par les références figées, avec leurs
empreintes. `pg_dump --snapshot` utilise le même état, avant ces écritures. La base et le lac
sources de test sont supprimés avant la restauration.
Après `pg_restore` dans la seconde base, elle vérifie les empreintes des fichiers,
la connexion, les membres, le coût, la séquence des événements, le journal,
l’index, le stock et Gold. Les bases et fichiers temporaires sont ensuite nettoyés.

Cette preuve vérifie que les écritures postérieures au gel sont exclues de la
restauration. Les références du journal et le dump proviennent du même instantané,
même si de nouveaux fichiers sont publiés avant leur copie. La fixture ne lance
aucune suppression externe concurrente. Le détenteur de l’instantané conserve
un verrou partagé de maintenance jusqu’à la fin du dump et des copies ; la
commande de nettoyage Nexora exige le verrou exclusif correspondant.
Les références du mode historique et des autres namespaces ne sont pas incluses.
Le stockage de secours externe et les exercices à l’échelle du parc restent
à mettre en place. La commande ne sauvegarde ni ne supprime la base `sam` ou MinIO.

### Rotation des lots en attente de reprise

Chaque passe de `nexora collect recover` examine d’abord les lots jamais
examinés, puis les moins récemment examinés. La date d’examen est persistée dans
PostgreSQL avant la lecture de Bronze : un lot ancien sans métadonnées de reprise,
ou dont la configuration a changé, ne monopolise donc pas indéfiniment le lot
borné de candidats. Une interruption après sélection laisse les lots éligibles
pour une passe ultérieure. La consultation simple des candidats ne change pas
cet ordre.

Cette sélection ne remplace pas le bail de traitement. La reprise acquiert toujours
le bail et son jeton avant de modifier les checkpoints ou de publier. Les imports
en attente d’activation et les workers avec un bail actif restent exclus.
La rotation est testée avec PostgreSQL et un lot bloqué suivi d’un lot publiable,
y compris après recréation du journal. Le worker ci-dessous ajoute le déclenchement
périodique de la reprise et la temporisation progressive des échecs techniques.

### Worker périodique de reprise

Après migration et activation validée du mode journalisé, lancer depuis `nexora/` :

```sh
nexora collect recover --watch --limit 10 --interval 300 --max-interval 3600
```

Sans `--watch`, la commande conserve sa passe unique. En mode périodique, elle
attend après la fin de chaque passe : les passes ne se chevauchent pas dans ce
processus. Les échecs techniques doublent progressivement le délai, jusqu’au
plafond configuré ; une passe sans échec technique rétablit le délai initial.
Les diagnostics nécessitant une intervention restent dans les résultats, sans
empêcher la rotation des autres lots. Les exceptions brutes ne sont pas journalisées.

SIGTERM ou SIGINT interrompt l’attente et empêche de prendre un nouveau lot. Le
traitement en cours termine normalement ; si l’hébergeur tue le processus avant
sa fin, le bail expiré et les checkpoints permettent la reprise. Prévoir un délai
d’arrêt adapté aux traitements Spark. Le délai entre passes repart à sa valeur
initiale après redémarrage ; les checkpoints et l’ordre d’examen restent persistés.
Les tests du CLI lancent des processus enfants et leur envoient réellement SIGTERM
et SIGINT, pendant une attente et pendant une passe simulée. Ils vérifient la fin
de cette passe, l’absence de passe supplémentaire et un code de sortie nul.
Ils ne simulent pas un blocage natif de Spark. Le gestionnaire de déploiement doit
relancer le worker après un arrêt inattendu.

Ce worker ne collecte pas de nouvelles journées et n’active pas un import préparé.
Le déclenchement de la collecte quotidienne reste à raccorder au contrat de
disponibilité DIGIMON. Il n’est pas activé dans la démonstration historique.

### Présence du worker et progression

Le worker périodique enregistre sa présence toutes les 30 secondes dans
`recovery_workers`, par source, périmètre et préfixe du lac. La commande
`collection_status` expose la dernière instance démarrée, son état, la dernière
présence, le début et la fin de passe, le résultat et la prochaine passe attendue.
Après 90 secondes sans présence, une instance en traitement ou en attente est
signalée silencieuse. Une erreur de renouvellement demande l’arrêt du worker ;
elle ne lui donne aucun droit supplémentaire de publication.

Une présence récente ne prouve pas la progression du traitement. Les dates de
passe et les checkpoints du journal restent distincts ; un appel Spark bloqué peut
coexister avec une présence récente. Un arrêt propre est affiché comme tel. Avec `--require-worker`, la commande
signale aussi l’absence d’instance répondant aux contrôles de présence et de délai.
Le gestionnaire de déploiement doit la relancer selon sa politique. Le détail
concerne la dernière instance ; les compteurs couvrent toutes les instances actives
du même préfixe, de la même source et du même périmètre. Les enregistrements de présence
ne contiennent ni payload, ni identifiants de connexion, ni exception brute.


Pour superviser un déploiement où la reprise périodique est attendue, ajouter
`--require-worker` à `nexora collect status --from … --through …`.
La commande sort avec le code 1 si aucun worker ne répond aux contrôles, y compris
après un arrêt propre. Sans cette option, l’absence de worker n’est pas une anomalie.
Les instances actives silencieuses et les passes en attente dépassant leur date
prévue de plus de 90 secondes sont signalées, même si une autre instance fonctionne.
Une présence récente ne masque donc pas une passe qui n’a pas commencé à temps.
Un traitement déjà commencé reste à surveiller via ses checkpoints et sa durée ;
aucune durée maximale universelle de calcul Spark n’est présumée ici.

### Déploiement local du worker avec Compose

Le profil `recovery` ajoute un service `recovery-worker`, sans port entrant ni
identifiants des comptes de démonstration. Il partage la configuration du lac,
le mode de collecte, la source et le périmètre avec le backend. Il attend que le
backend réponde à `/health` ; le démarrage normal du backend applique d’abord les
migrations. Le profil reste désactivé lors d’un `docker compose up` ordinaire.

Après validation et activation de l’import existant, configurer
`COLLECTION_ENABLED=true` dans l’environnement commun, puis lancer :

```sh
docker compose --profile recovery up -d --build recovery-worker
```

Le service utilise un processus init, accorde cinq minutes à l’arrêt et autorise
jusqu’à cinq redémarrages après échec. Un arrêt volontaire ne déclenche pas de
redémarrage. Les cinq minutes sont un réglage local à adapter aux durées Spark
mesurées. Ce profil vise la stack locale ; il ne configure pas un déploiement Safran.

La configuration Compose a été validée et l’image construite. Un conteneur du
service a exécuté plusieurs passes sur la base de test et un périmètre vide isolé,
puis a reçu un arrêt Docker : code de sortie 0, état PostgreSQL `stopped`, dernière
passe terminée et aucune passe suivante programmée. Le conteneur temporaire a été
retiré sans supprimer de volume. Cet essai valide le cycle du worker, pas une
collecte DIGIMON réelle ni un traitement Spark en cours d’arrêt.

### Reprise après restauration complète

L’exercice `workflow/verify-collection-restore.py` inclut aussi un second lot,
interrompu après son checkpoint Bronze, et une ancienne présence de worker.
Il sauvegarde PostgreSQL et les dépendances des deux lots, puis supprime la base
et le lac sources de la fixture avant de restaurer dans une autre base.

La vérification retrouve le résumé de catalogue matérialisé, l’ordre d’examen des
reprises et la présence silencieuse du worker. Elle reprend ensuite le lot depuis
le Bronze restauré, avec Spark, sans connecteur source. Le même identifiant est
publié ; une nouvelle passe de reprise ne trouve plus ce lot. L’exécution locale
a vérifié 22 fichiers, 120 machines, 12 pools et 24 relevés sur deux journées.
Les bases et fichiers temporaires sont supprimés à la fin de l’exercice.

Cela valide la restauration de l’état figé de la fixture et la reprise après
restauration, malgré des écritures ultérieures dans la source. La coordination
générale des références et de la rétention, le stockage de secours externe et
les procédures de basculement de production restent à valider.

### Inventaire des références à préserver

`nexora lake retention` parcourt les checkpoints courants,
les checkpoints archivés après changement de référence et les têtes publiées de
tous les runs du préfixe actif, sans exclure les runs rejetés ou non publiés.
La lecture des racines utilise un snapshot PostgreSQL cohérent ; leurs manifestes
sont ensuite suivis par l’inventaire des dépendances. Une référence JSON manquante
interrompt la commande. Le rapport ne contient pas les payloads source.

Sur l’import préparé local, le rapport retrouve quatre artefacts racines, sept
objets et douze versions Delta. Aucune suppression ni activation n’a été effectuée.
Les tests couvrent un import en attente, un checkpoint archivé, l’isolation du
préfixe et l’échec sur un manifeste absent.

Ce rapport décrit les références du journal à l’instant de sa lecture. Il ne couvre
pas à lui seul les références du mode historique, les sauvegardes externes ou les
écritures en cours qui n’ont pas encore de checkpoint. Il ne doit pas servir de
liste blanche pour supprimer le reste du bucket. Une future purge doit intégrer
ces références et un protocole d’exclusion avec les traitements et sauvegardes ;
`deletion_authorized` reste donc toujours faux.

### Conflit de révision pendant une reprise

Avant de recalculer une journée, la reprise compare sa référence Bronze avec
celle déjà publiée pour cette journée. Si le contenu diffère et que le lot publié
a été enregistré après le candidat interrompu, la reprise est rejetée avec
`DAY_REVISION_CONFLICT`. La journée publiée reste intacte ; le Bronze et l’historique
du candidat restent disponibles pour examen. La passe automatique ne réessaie
pas ce rejet sans intervention.

Ce contrôle est conservateur : l’ordre d’enregistrement local ne prouve pas l’ordre
des révisions source. Il bloque une ambiguïté connue, sans comparer lexicalement
des identifiants opaques. Il ne détecte pas une vieille révision inconnue arrivant
pour la première fois après une correction. Un numéro de séquence ou une relation
explicite de remplacement doit encore être convenu dans le contrat DIGIMON réel.
Le test reproduit une interruption, la publication d’un contenu différent pour
la même journée, puis la reprise ancienne ; il vérifie le rejet et la conservation
des valeurs corrigées. Les corrections nouvellement enregistrées et les reprises
de journées distinctes restent couvertes par la suite.

### Disponibilité des journées et tentatives

Le batch journalise désormais sa tentative avant d’appeler l’adaptateur de
disponibilité. `daily_collection_polls` conserve, par préfixe/source/périmètre/jour,
le numéro de tentative, son début, sa fin, son résultat et le run éventuel.
Une source pas encore prête est `source_pending` ; un appel interrompu laisse
`fetching` sans fin enregistrée. Ce dernier état ne prouve pas à lui seul que le
processus est mort : les dates et la supervision restent nécessaires.

La commande de statut expose ces résultats dans la fenêtre demandée, avec un
nombre de détails borné. Une tentative technique échouée reste visible même si
une ancienne version de la journée est déjà publiée. Une réponse tardive ne peut
pas remplacer le diagnostic d’une tentative plus récente. Ces métadonnées suivent
la dernière tentative de chaque jour ; elles ne remplacent ni les checkpoints,
ni le pointeur de publication, ni un historique exhaustif des appels HTTP.

Les tests couvrent une journée retardée puis rattrapée, le comptage des tentatives,
une réponse ancienne, une interruption avant réception et l’isolation des périmètres.
La boucle quotidienne alimente ces tentatives ; son raccordement à l’adaptateur
DIGIMON réel et son déploiement restent nécessaires en production.

Une tentative échouée après réception est reliée au run créé. Si une reprise
publie ce run, la supervision expose `recovered` comme état effectif, tout en
conservant `attempt_status=failed` et l’état publié du run. Cette résolution
évite une alerte persistante après récupération effective. Un échec avant
réception, sans run associé, reste un échec ; il n’est pas masqué par la présence
d’une autre journée publiée. Le test couvre trois journées interrompues puis
reprises depuis Bronze, sans nouvel appel à la source.

### Exclusion entre sauvegarde et suppression

`protect_backup` prend un verrou consultatif PostgreSQL partagé, conservé par
la transaction de `hold_backup_snapshot`. `protect_deletion` exige le même
verrou en mode exclusif avant le nettoyage historique. Une opération incompatible
est refusée immédiatement ; elle doit être retentée après la fin de l’autre.
Les verrous sont libérés à la fin de la transaction, y compris après rollback.
Les collectes ordinaires ne prennent pas ce verrou et continuent à publier.

Les tests PostgreSQL vérifient deux sauvegardes simultanées, le maintien de la
protection jusqu’au dernier lecteur, l’exclusion de deux purges, le refus d’une
sauvegarde pendant une purge et la libération après rollback. La restauration
isolée utilise aussi ce verrou pendant la copie des objets et le dump.

La portée est toute la base PostgreSQL, tous namespaces confondus, car le
nettoyage historique parcourt le bucket. Tous les services partageant un même
lac doivent utiliser cette même coordination. Ce verrou coopératif ne bloque
ni un administrateur MinIO, ni une règle de lifecycle, ni un VACUUM externe.
Toute future commande de purge doit conserver le verrou exclusif pendant ses
suppressions, puis vérifier les références : obtenir le verrou seul n’autorise
pas à supprimer une version encore utilisée. Aucune purge Delta n’est activée.

### Identifiants source non valides

Le DTO provisoire exige des chaînes non vides pour `poolKey`, `product.key` et
`product.name`. Une valeur nulle, booléenne, numérique ou structurée n’est plus
convertie en nom de produit ou identifiant artificiel. Le mode journalisé archive
le payload dans Bronze puis rejette le lot, sans publication ni reprise infinie.
Si le contrat réel emploie des identifiants numériques, leur encodage devra être
explicité dans l’adaptateur validé avec DIGIMON.

### Journée et fuseau de la source

Le DTO provisoire exige un `capturedAt` ISO avec décalage explicite (`Z` ou
`+02:00`, par exemple). Une date seule ou une heure sans fuseau est rejetée.
La journée de collecte reste celle du calendrier porté par ce décalage ; elle
n’est pas implicitement convertie dans le fuseau du serveur. L’adaptateur réel
DIGIMON devra confirmer la définition de la journée métier, notamment pour les
sites internationaux. Le contrôle `expected_day` vérifie ensuite cette journée.
Les lots sans fuseau restent archivés dans Bronze mais ne sont pas publiés.

### Boucle de collecte quotidienne

`run_daily_worker` interroge périodiquement un adaptateur `DailySource` sur la
journée courante et une fenêtre récente configurable (7 jours par défaut,
366 au maximum). L’horloge doit fournir un fuseau explicite. La fenêtre est
recalculée à chaque passe ; l’adaptateur décide si chaque journée est disponible.
`source_pending` est une attente normale, sans alerte d’échec. Les erreurs
entraînent les délais progressifs du worker, sans chevauchement dans le processus.
Les journées déjà publiées sont réinterrogées pour détecter les corrections.

L’arrêt demandé laisse finir la journée commencée et empêche d’en commencer une
autre. Les tests utilisent de vrais journaux PostgreSQL et tables Delta pour
vérifier une journée retardée, une révision corrigée, trois passes sans doublons
et un arrêt demandé pendant la lecture source. Les tentatives restent persistées
par `collect_days`.

Ce composant n’est pas encore lancé par un service Docker : l’adaptateur de
disponibilité DIGIMON et la supervision propre au collecteur restent à intégrer.
Sans `history_start`, les trous plus anciens que la fenêtre nécessitent une
passe explicite. Avec cette date configurée, chaque passage traite aussi un
quota de journées anciennes (10 par défaut, 100 au maximum), sur au plus
3 660 jours. Les dates jamais interrogées passent en premier, puis celles dont
la dernière tentative est la plus ancienne. Cette priorité repose sur les
métadonnées PostgreSQL et subsiste après un redémarrage. Une journée toujours
indisponible ne bloque donc pas les suivantes. Les anciennes dates publiées sont
aussi revisitées pour leurs corrections. Le quota limite les appels par passage,
pas le coût d’un relevé ; la sélection n’est pas un bail entre collecteurs.

### Minimums attendus avant toute référence historique

`COLLECTION_MINIMUM_COUNTS` accepte un objet JSON de compteurs minimums, par
exemple `{"machines":100,"machines/subsidiary/A":40}` pour un scénario de test.
Les clés suivent les dimensions du profil de couverture : totaux, machines ou
utilisateurs par filiale, installations par identifiant de produit, droits par
produit/filiale/métrique. Une dimension absente vaut zéro pour ce contrôle.
Les nombres doivent être des entiers positifs ou nuls, sans conversion implicite.
La variable doit être passée au processus backend et aux workers ; elle n’est
pas injectée par défaut dans le fichier Compose.

Ces minimums s’appliquent dès le premier lot et aux corrections historiques.
Un manque conserve Bronze et le diagnostic `shortfalls`, mais interdit la
publication. Les seuils sont inclus dans l’identité de transformation : une
modification demande une nouvelle validation. Sans minimum configuré, l’identité
historique reste compatible et aucun volume attendu n’est inventé. L’absence
de référence reste explicitement indiquée ; ces seuils ne prouvent pas à eux
seuls que DIGIMON a transmis toutes les données. Leurs valeurs et leur applicabilité
aux anciennes journées doivent être convenues avec la source avant activation.

### Taille des diagnostics de supervision

Le statut conserve les totaux de baisses et de minimums non atteints, mais limite
chaque liste à 100 dimensions par rejet par défaut (`quality_limit`, au maximum
1 000). Cette projection est effectuée dans PostgreSQL avant transfert du rapport.
Les indicateurs `decreases_truncated` et `shortfalls_truncated` signalent qu’il
reste des dimensions à examiner. Le nombre de minimums configurés est fourni,
sans recopier toute la politique dans le statut. Le checkpoint `validated`
conserve la politique et le diagnostic complets pour l’analyse du rejet.

### Rejets de qualité corrigés

Le statut distingue les rejets historiques des alertes encore actives. Un rejet
`COVERAGE_DECREASE` est résolu seulement si une collecte enregistrée plus tard,
du même flux et avec le même identifiant source, a publié le Bronze actuellement
référencé pour cette journée dans le manifeste consulté. Publier une autre journée
ne suffit pas. Le compteur `resolved_quality_rejections` signale ces cas ; les
runs rejetés et leurs checkpoints restent inchangés dans le journal.

Les erreurs sans journée validée ou sans correspondance certaine restent des
alertes à examiner. Ce mécanisme ne supprime pas les diagnostics de tentative
HTTP : une tentative récente échouée peut encore justifier une alerte distincte.

### Candidat de compaction Delta

`DeltaTables.compact(reference)` compacte la version courante d’une table avec
une cible de 128 MiB et une seule tâche concurrente. La cible est bornée entre
1 MiB et 1 GiB. Une référence devenue ancienne est refusée avant l’opération.
Le commit porte un identifiant Nexora pour retrouver exactement la version
produite, sans choisir par erreur le dernier commit d’un autre écrivain.
Une seconde compaction sans changement est sans effet.

Le test local crée cinq petits fichiers, vérifie leur réduction et compare les
lignes avant/après. Il relit aussi la première version et vérifie la présence des
anciens fichiers. Aucune commande VACUUM n’est exécutée. L’opération renvoie une
référence candidate ; les manifestes publiés continuent à lire leur version
épinglée. Pour bénéficier de la compaction dans les consultations, il reste à
valider la candidate puis la publier par le mécanisme de changement de manifeste,
en coordonnant les écritures. Aucun planificateur de compaction n’est activé.

### Référence exacte lors de la publication

La publication compare sous verrou l’identifiant du lot **et** la clé du manifeste
ayant servi de référence. Un manifeste différent, même rattaché au même lot,
provoque un conflit. La réconciliation détecte aussi ce changement et archive les
checkpoints dérivés avant recalcul, en conservant Bronze. Cette garde prépare
les changements de références liés à la maintenance ; elle ne publie pas encore
les candidats de compaction.

### Adoption atomique d’un manifeste de maintenance

Le journal peut adopter un manifeste préalablement vérifié pour un lot publié.
Il verrouille le lot puis sa publication, compare la référence attendue, archive
l’ancien checkpoint Gold et remplace le checkpoint et le pointeur dans la même
transaction. Une candidate préparée sur une ancienne référence est refusée.
Les lecteurs prennent le pointeur et son checkpoint dans une seule lecture SQL,
pour ne pas mélanger les deux versions pendant ce changement.

Ce composant ne vérifie pas lui-même les tables : le coordinateur doit comparer
les données, conserver l’identité du lot et vérifier les empreintes avant l’appel.
Le coordinateur décrit ci-dessous raccorde ces étapes pour les usages d’une
journée ; sa planification et son extension aux autres tables restent à terminer.

### Coordinateur de compaction d’une journée

`compact_usage_day` relie compaction, comparaison des données et adoption atomique
pour les usages d’une journée publiée. Il compare schéma, nombre et contenu des
lignes, puis écrit et relit le manifeste avant adoption. Une publication concurrente
fait échouer l’adoption ; le lot plus récent reste actif. Le manifeste précédent
et le détail avant/après restent référencés pour la traçabilité et la sauvegarde.

Une interruption après compaction laisse l’ancien manifeste actif. La relance
peut reprendre la candidate si son commit porte la marque de compaction et la
version initiale attendue ; elle recommence la comparaison. Un changement de table
sans cette provenance est refusé. Les objets de manifestes écrits avant une
interruption peuvent rester orphelins : aucune suppression automatique n’est faite.

Les tests locaux couvrent une interruption avant adoption, une relance sans
doublon, une collecte concurrente et une candidate aux valeurs altérées. La
comparaison charge les données de la journée en mémoire et les trie : ce chemin
n’est pas encore dimensionné pour une maintenance générale du parc d’entreprise.
Il n’est pas planifié et n’exécute pas VACUUM. Les tables d’inventaire et de BI
ne sont pas encore prises en charge par ce coordinateur.

### Restauration des références après compaction

Un test croisé part d’une publication fragmentée, la compacte et l’adopte, puis
énumère les dépendances du journal. Il copie uniquement les objets et fichiers
Delta listés dans un autre répertoire, supprime le lac source de la fixture et
relit la publication compactée ainsi que sa version précédente. Les deux lectures
retrouvent les mêmes lignes. Le test vérifie donc que l’archivage du checkpoint
et la chaîne des manifestes alimentent correctement le plan de sauvegarde.
PostgreSQL reste en place dans cet exercice ; la restauration de la base complète
est couverte séparément par `workflow/verify-collection-restore.py`.

### Commande de compaction manuelle

Dans un environnement où la collecte journalisée a déjà été validée et activée :

```sh
nexora lake compact --day "$JOUR_A_COMPACTER"
nexora lake compact --day "$JOUR_A_COMPACTER" --target-mib 128 --apply
```

La première commande ne modifie ni table ni publication : elle affiche la
référence publiée, la version courante et le nombre de fichiers de la table.
Pour une référence filtrée par journée, ce nombre concerne toute la table.
`--apply` exécute le coordinateur et sa validation ; une référence obsolète
provoque un code de sortie non nul. Le script refuse le mode historique et
n’active pas lui-même la collecte. Les erreurs techniques sont rendues sous forme
de codes sans recopier les exceptions susceptibles de contenir des identifiants.
Aucune planification ni suppression de versions n’est déclenchée par cette commande.

### Supervision de la collecte quotidienne

`run_supervised_daily_worker` encadre le polling de disponibilité avec une présence
persistée, le début et la fin de chaque passage et un arrêt enregistré. Une panne
de heartbeat demande l’arrêt ; une sortie exceptionnelle est conservée comme échec.
La migration `0018_worker_roles` distingue les rôles `daily` et `recovery`.
Le diagnostic existant de reprise filtre uniquement `recovery` : la présence d’un
collecteur quotidien ne peut pas masquer l’absence du worker de reprise.

Ce point d’entrée interne attend toujours un adaptateur `DailySource` qui garantit
la disponibilité du relevé. Il n’invente pas de route DIGIMON ni de signal de
complétude à partir de l’heure. Le branchement au service déployé reste à terminer. La collecte de la démo reste désactivée.

Le diagnostic `collection_status` expose séparément `daily_worker` / `daily_workers`
et `recovery_worker` / `recovery_workers`. Le CLI accepte `--require-daily-worker`
en complément de `--require-worker`. Chaque rôle déclenche sa propre alerte en
cas d’absence requise, de heartbeat silencieux ou de prochain passage dépassé.
Un rôle en bonne santé ne satisfait jamais l’exigence de l’autre. L’heure du dernier
passage terminé reste distincte de celle du heartbeat : la présence seule ne
prouve pas la publication d’un relevé.

L’exercice `workflow/verify-collection-restore.py` restaure également les rôles des
workers et les identités BI. Le contrôle exécuté retrouve 120 machines, 12 pools,
30 fichiers vérifiés et deux instantanés BI ; le lot interrompu reprend jusqu’à
24 observations. Un jeton révoqué avant le point de sauvegarde reste refusé et un
jeton créé après ce point n’existe pas dans la restauration. Un collecteur quotidien
en échec conserve son rôle et son alerte, indépendamment du worker de reprise
silencieux. Les bases et fichiers de cet exercice sont temporaires et supprimés.
Cette preuve ne couvre pas les révocations effectuées après le point sauvegardé :
leur réconciliation reste nécessaire avant réouverture des accès restaurés.

### Point d’entrée du collecteur quotidien

`nexora collect run --timezone Europe/Paris --once` effectue un
passage supervisé ; omettre `--once` répète les passages. `--lookback-days`,
`--history-start`, `--catchup-limit`, `--interval` et `--max-interval` règlent la
fenêtre récente, le rattrapage et les délais. SIGTERM/SIGINT demandent l’arrêt entre
journées, après la fin de la journée en cours. Le code de sortie est non nul en
cas d’échec ou d’attention requise au dernier passage.

Le point d’entrée exige `COLLECTION_ENABLED=true` et un connecteur offrant
`ready_snapshot(day)` selon le protocole `DailySource`. Les connecteurs actuels
n’offrent pas encore le contrat réel de disponibilité : le lancement refuse alors
avec `DAILY_READINESS_CONTRACT_REQUIRED`, sans appeler le snapshot courant. Aucun
profil quotidien n’est activé dans Compose. Les essais du CLI utilisent un
adaptateur fictif explicite et vérifient répétition sans doublons, arrêt supervisé
et absence d’accès au lac lorsque la collecte est désactivée.

### Archive complète avant restauration

L’exercice de sauvegarde utilise désormais `backup_archive.seal_archive` après le
dump et la copie. Il vérifie les empreintes du dump, des métadonnées figées et des
fichiers du lac, puis publie une seule fois `backup-complete.json`. Une copie
incomplète ne peut pas produire ce marqueur. Avant `pg_restore`, `verify_archive`
revérifie chaque fichier, sans charger le dump en mémoire. Les chemins sortant de
l’archive sont refusés et une archive déjà scellée n’est pas remplacée.

Cette étape détecte les fichiers manquants et les corruptions de transport ou de
stockage. Ce manifeste n’est pas une signature et suppose un emplacement de
sauvegarde protégé. L’archive doit rester immuable après validation. L’exercice
reste isolé et temporaire ; la destination de sauvegarde d’exploitation, ses droits,
son chiffrement et sa rétention restent à configurer et tester.

### Validation du backend démarré

Le backend Docker local a été reconstruit et redémarré après sauvegarde privée de
la base de démonstration. La base a atteint `0018_worker_roles`. Le service répond
sur `/health`, refuse les lectures analytiques sans authentification et garde BI
inaccessible (`BI_ENABLED=false`). `COLLECTION_ENABLED=false` et la source mock
restent inchangés : cette mise à jour n’active pas l’import ni la collecte.

Le benchmark authentifié du service démarré a vérifié machines, catalogue logiciel
et usages d’installation sans erreur. Avec deux lectures concurrentes et deux
répétitions par route, les médianes locales observées sont respectivement 308,1 ms,
57,5 ms et 32,6 ms. Ce contrôle ne remplace pas une validation visuelle du frontend,
une charge prolongée, Power BI ou le réseau cible.

### Vérification d’un import préparé

`nexora lake import --verify-artifact <fichier.json>`
revérifie un artefact préparé sans activer de publication et sans prendre de bail.
Le contrôle compare les références du parc, les comptages des versions Delta, le
manifeste d’inventaire et les paramètres d’analyse. Un changement des seuils ou de
la réserve depuis la préparation impose une nouvelle préparation ; l’activation
applique désormais ce même contrôle. Les anciens producteurs doivent toujours
être arrêtés avant l’activation : cette lecture seule n’installe pas de verrou sur
eux et ne remplace pas la vérification finale.

La vérification locale de l’import préparé a confirmé les références et comptages :
365 jours d’observations d’inventaire (92 345 000 lignes), 365 jours d’usage produit
(241 082 500 lignes), 138 500 machines, 126 500 utilisateurs, 180 sites, 30 produits
et 360 lignes de licences. Le journal n’a toujours aucun pointeur actif pour ce
flux : la vérification n’a pas activé la collecte. Ces comptages ne constituent pas
une validation des données réelles DIGIMON ni de chaque valeur métier fictive.

Les tentatives quotidiennes restées `fetching` au-delà de
`collection_status --poll-timeout-seconds` (3 600 secondes par défaut) sont
signalées `overdue`, même si la journée possède une publication antérieure.
Il s’agit d’un seuil d’attention configurable, pas d’une preuve d’arrêt : le
statut original reste visible et aucune tentative ni publication n’est annulée.

Avant de publier `backup-complete.json`, le scellement vérifie les empreintes,
synchronise chaque fichier puis les répertoires enfants et parents. Une erreur
de synchronisation des membres empêche la publication du marqueur. Le répertoire
d’archive doit rester privé et immuable pendant cette opération. Cette séquence
s’appuie sur les garanties `fsync` du stockage ; elle ne constitue pas un test de
panne électrique ni une certification de durabilité du stockage distant.

Le plan `required_archive_members` est enregistré dans `snapshot.json` avant la
copie, à partir des dépendances de l’instantané figé. Scellement et vérification
exigent toutes ces entrées dans la liste des empreintes : omettre à la fois un
fichier et son empreinte ne permet plus de déclarer l’archive complète. Une archive
sans ce plan est refusée ; aucun plan n’est déduit des seuls fichiers présents.
Le test de restauration isolée a été rejoué avec ce contrôle : 40 fichiers et
quatre instantanés BI restaurés, reprise du lot interrompu et accès vérifiés.
