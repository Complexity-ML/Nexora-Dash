# Inventaire et historique d’entreprise

Le scénario fictif contient 110 000 salariés et 16 500 prestataires, 116 500 postes de travail,
2 000 hôtes physiques et 20 000 VM. Il répartit le parc sur 180 sites et utilise
les libellés fournis : SAE, SED, SHE, SLS, SAB, SNA, SST, STS, SAO, SCA,
SAFRAN GROUP et SAFRAN SIÈGE. Les implantations, effectifs, configurations et
usages sont inventés ; ils ne décrivent pas ces entités réelles.

Le modèle relie les entités, sites (pays, région, ville), utilisateurs,
machines et observations logicielles. Les VM référencent leur hôte et partagent
sa localisation. Les serveurs couvrent Red Hat/KVM, Red Hat/Nginx/PostgreSQL et
Windows Server/IIS. Les utilisateurs sont anonymes, avec des adresses réservées
sous `example.invalid`.

## Lac et consultation

MinIO conserve les archives Bronze et les tables Delta Silver. Les dimensions du scénario
sont immuables et communes aux journées ; les 253 000 observations par jour sont
partitionnées par date, soit 92 345 000 observations sur 365 jours. Le manifeste
référence les dimensions et toutes les partitions. La présence d’usage et la durée quotidienne facultative ne sont
pas des mesures de simultanéité : ne pas la comparer directement aux
capacités des 12 pools du scénario analytique, qui reste un jeu distinct.

PostgreSQL porte un index de consultation reconstruisible, avec une ligne par
machine, utilisateur ou site. Le service Python filtre et pagine côté serveur (100 résultats
maximum), puis fournit les relations de l’élément ouvert. Les dashboards en cartes
permettent d’ouvrir une entité, un site ou une catégorie avant d’accéder aux détails.
Les périmètres logiciels des espaces sont appliqués aux listes et relations.
Les VM sans observation liée à un pool restent visibles dans le catalogue complet,
mais ne sont pas incluses dans un périmètre de pools auquel elles ne sont pas liées.

## Création de la démonstration

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps dash nexora dev demo inventory
```

Le script refuse les sources réelles. Il crée un namespace déterministe dépendant
des dimensions du scénario et de la durée, vérifie les nombres de lignes des tables Delta,
puis publie l’index dans une transaction. Les versions précédentes restent
conservées. Relancer un scénario identique réutilise ses partitions quotidiennes.
Les coûts, dossiers, comptes et relevés agrégés des pools ne sont pas réinitialisés.
L’index présente le dernier relevé du scénario, et les fichiers quotidiens restent
dans le lac. Une modification des données d’inventaire exige une reconstruction
de cet index avec le script ; la synchronisation des pools est indépendante.

Le petit jeu de 120 machines reste disponible pour les tests et la génération
initiale des pools. `nexora dev demo legacy-inventory` enrichit les anciens lacs de ce
petit inventaire ; ce n’est pas le scénario d’entreprise.

## Contrat DIGIMON provisoire

Le payload peut contenir `inventory` avec les listes `subsidiaries`, `sites`,
`machines`, `users`, `observations` définies dans `app/models/inventory.py`.
Les identifiants inconnus, doublons et cycles entre hôtes sont refusés avant écriture.
Sans ce champ, aucun inventaire réel n’est synthétisé. Le mapping et la collecte
automatique de la véritable source restent à définir avec l’équipe DIGIMON.

Un Data Lake n’impose pas Spark. Le choix du moteur dépend des volumes quotidiens,
de la conservation et des calculs. Le test local du scénario ne prouve pas les
performances dans le réseau et l’infrastructure de production.

### Provenance et usages transmis par DIGIMON

Nexora reçoit uniquement les données de DIGIMON. La collecte auprès des agents
SCCM/Flexera relève de DIGIMON ; Nexora ne se raccorde pas aux agents.
Le champ facultatif `digimon_reported_source` représente la provenance indiquée
par DIGIMON. Dans le scénario fictif, les valeurs SCCM (Windows) et Flexera One
(Linux) simulent cette métadonnée ; cette répartition reste une hypothèse de démonstration.
Les observations contiennent une version logicielle fictive, une durée quotidienne
par machine/utilisateur/logiciel en minutes et un nombre d’exécutions. Une durée
absente reste `null` et s’affiche « Non renseigné » ; elle ne vaut pas zéro.
Ces champs sont facultatifs pour accepter un inventaire sans télémétrie d’usage.
Les partitions `enterprise-v6` isolent ce scénario des anciennes générations.

La génération `enterprise-v3` répartit les salariés selon des poids fictifs distincts
par filiale et par site. La répartition des serveurs diffère de celle des postes.
Le siège et le groupe privilégient les fonctions support ; les autres entités
ont des profils industriels. Ces poids ne décrivent pas les effectifs réels Safran.
Les totaux restent 126 500 personnes et 138 500 machines, dont 20 000 VM.

La génération enterprise-v6 couvre 180 sites fictifs : 34 SAE, 26 SED, 18 SHE, 22 SLS, 10 SAB, 14 SNA, 16 SST, 6 STS, 14 SAO, 14 SCA, 3 SAFRAN GROUP et 3 SAFRAN SIÈGE. Les implantations et ces volumes sont des hypothèses de démonstration.

## Architecture cible

Agents → Beacon général → backend DIGIMON Node.js → API REST DIGIMON → collecteur Nexora Python → MinIO et analyses. L’interface Dash pourra être exposée sous une route de DIGIMON, avec le reverse proxy et l’authentification à convenir avec son développeur. Le prototype reste exécutable seul pour la démonstration. Aucun accès direct au Beacon depuis Nexora.

Les 16 500 prestataires fictifs (hypothèse de 15 % des salariés) disposent chacun d’un portable dédié et de logiciels installés liés à leurs observations. Les salariés utilisent 100 000 postes, dont certains partagés. Le modèle distingue `employment_type` et `form_factor`.


### Catalogue, installations et licences

Le modèle distingue les produits (`products`), les installations par machine
(`installations`) et les droits (`entitlements`). Les identifiants sont stables ;
les références vers un produit, une machine ou une filiale inexistante sont rejetées.
Un droit précise son unité : utilisateur nommé, appareil, concurrence, cœur ou hôte.
Une quantité d’installation ne prouve pas une consommation contractuelle.

Le scénario d’entreprise contient des quantités et unités fictives par produit et
filiale, ainsi que des composants sans décompte. Ces hypothèses servent à tester le
modèle et ne décrivent pas les règles commerciales des éditeurs. Une installation
sans activité n’établit pas à elle seule un droit libérable. Les simulations
financières doivent conserver l’unité du contrat et un coût renseigné.


### Analyse des installations persistées

`nexora/devtools/demo/analyze_enterprise_installations.py` lit les partitions quotidiennes
actives et publie un agrégat Gold par couple machine–logiciel. Les usages de plusieurs
personnes sur une machine sont réunis. Les journées absentes restent distinctes des
journées observées sans usage. Le rapport n’est activé que si la génération courante
n’a pas changé pendant le calcul.

Le service Python `inventory_service.installation_usage` ne retourne que les logiciels
suivis par l’espace. Cette analyse produit une liste d’installations à examiner ; elle
ne convertit pas automatiquement ces installations en licences libérables ni en euros.
Les observations initiales couvrent douze produits applicatifs. Le script
`seed_enterprise_product_usage` complète les dix-huit systèmes, services et
applications sans pool, selon le protocole ci-dessous.

La page FlexLM utilise uniquement `licenseManager` explicitement fourni par la source
(`flexnet` ou `flexlm`). Le scénario déclare neuf pools FlexNet ; il s’agit d’un choix
de simulation, pas d’une règle déduite du nom d’un éditeur. Une valeur absente reste
non classée. Les autres pools sont exclus des compteurs FlexLM.

## Périmètres de tous les produits

Le catalogue de sélection fusionne les pools historiques et les produits installés de la génération MinIO active. RHEL, Windows, Microsoft 365 et les composants sans pool sont sélectionnables. Le champ de sélection `pool_ids` conserve son nom pour compatibilité ; il transporte aussi les identifiants stables `software_id` des produits sans pool. Une capacité absente reste nulle.

L’index associe les produits installés aux machines, à leurs sites et aux utilisateurs reliés par les observations. Les droits globaux ne sont pas automatiquement attribués à un espace partiel. Après évolution de la projection, `nexora dev demo reindex` reconstruit l’index depuis la génération active et conserve son manifeste, ses partitions et ses résultats analytiques. Le basculement est refusé si la génération active a changé pendant la reconstruction.

### Examiner les installations sans usage

Dans Coûts & économies, « Examiner » ouvre une liste paginée des machines du
produit sans usage sur toute la période. Le service Python
`inventory_service.installation_usage_machines` croise la table Delta
Gold avec les machines de la projection active et le périmètre de l’espace.
Elle exclut les relevés incomplets, les périodes différentes, les machines
absentes de l’inventaire actif et celles dont un utilisateur a utilisé le produit.
Chaque ligne permet de retrouver la machine dans l’inventaire. Cette sélection
constitue un examen, pas une décision de désinstallation ou une économie réalisée.

Sans projection PostgreSQL (démonstration fraîche ou réinitialisée), le catalogue
des installations et le catalogue de sélection sont reconstruits depuis le
dernier snapshot Silver. Les systèmes, applications et services des
anciens snapshots reçoivent des identifiants déterministes ; le périmètre reste
appliqué à la liste des logiciels et aux machines associées.

La réindexation vérifie sous le verrou de publication l’identifiant de génération
et la clé de son manifeste. Si une analyse a publié un nouveau manifeste entre
la lecture et la publication, elle échoue sans remplacer la génération active.
Relancer alors la réindexation pour repartir du manifeste à jour.

Les produits explicites sont identifiés par `software_id`, même lorsque plusieurs
produits ont le même nom. Les noms ne servent à synthétiser un identifiant que
pour les champs anciens OS/applications/services. Un nom ambigu sans installation
explicite ne reçoit pas arbitrairement un pool. La projection indexe les noms,
identifiants de produits et pools ; les liens vers les machines utilisent
l’identifiant stable du produit. Après cette évolution, reconstruire l’index.

La vue d’ensemble commence par les machines, utilisateurs, sites et produits
installés du périmètre. Sans historique de pool dans cet espace, elle présente
les produits et leur parc, sans taux d’utilisation ni graphiques de capacité à zéro.

## Historique des systèmes, services et applications sans pool

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps dash nexora dev demo usage
```

Cette extension de démonstration exige une source mock, une génération d’entreprise
active et son rapport initial d’installations. Elle ne contacte ni agent ni Beacon.
Elle simule les mesures que le futur contrat REST DIGIMON devra définir. Les
colonnes sont `installation_id`, `machine_id`, `software_id`, `observation_date`,
`measurement`, `observed`, `used` et `duration_minutes`.

`measurement` distingue le fonctionnement du système (`system_uptime`), l’activité
du service (`service_runtime`) et l’exécution applicative (`application_execution`).
Ces durées ne sont ni un nombre de licences simultanées ni une consommation
contractuelle. La durée d’une VM ne dépasse pas celle de son hôte. Les durées
applicatives restent dans la durée de fonctionnement de la machine. Les journées
non observées portent `observed=false`, `used=null`, `duration_minutes=null`.

Dans le scénario complet, 660 500 installations supplémentaires sont observées
chaque jour sur 365 jours, soit 241 082 500 relevés. Les installations applicatives
déjà analysées sont conservées ; l’agrégat réunit 912 500 installations et 30
produits. Les absences de mesure restent exclues des conclusions d’inactivité.

Chaque partition est enregistrée en Bronze et Silver puis relue pour calculer
l’agrégat Gold. Une reprise réutilise les partitions vérifiées. Les identifiants,
l’ordre des installations, les dates et les durées sont contrôlés. Le nouveau
rapport et son manifeste sont publiés dans un emplacement immuable ; l’activation
vérifie le run et le manifeste sous le verrou de publication. Les anciens rapports
restent actifs si les données changent pendant le calcul ou si un contrôle échoue.
Les dimensions, comptes, coûts et dossiers ne sont pas réécrits.

## Modèles de licence de la démonstration

Les 30 produits du scénario disposent d'un modèle fictif explicite : quantité par appareil, utilisateur nommé, capacité simultanée ou absence de décompte. Ces hypothèses ne décrivent pas les contrats des éditeurs. Un produit inconnu ne reçoit jamais automatiquement un modèle sans décompte.

`nexora dev demo licenses` complète uniquement la dimension des licences de la démo active, après contrôle de concurrence ; les observations, coûts et dossiers ne sont pas réécrits. La page présente les unités séparément et regroupe les éventuelles informations manquantes sans répéter un état vide sur chaque ligne.

### Provenance des licences fictives

Le fichier `nexora/app/connectors/demo_license_source.json` représente des réponses
DIGIMON fictives : quantités et unités explicites par produit et filiale, indépendantes
du nombre d’installations. Ce scénario ne décrit pas les contrats réels.

Seules les remontées Maple et ArcGIS Pro de STS sont volontairement absentes.
Les 28 autres produits ont une couverture complète. Une quantité absente
reste absente ; elle ne devient jamais zéro. Les logiciels sans décompte restent
identifiés séparément. Le tableau additionne uniquement les quantités reçues dans
une même unité et signale les totaux partiels, avec le détail par filiale.

`complete_demo_licenses.py` archive le payload source en Bronze, le relit avec le
mapping d’inventaire, valide et écrit les licences dans Delta avant activation.
Le manifeste conserve la référence Bronze. Les installations, usages, coûts et
anciens dossiers restent inchangés.

### Chargement des licences

La page Licences utilise `inventory/software?include_installations=false` pour lire
uniquement les dimensions produits, filiales et licences du manifeste actif.
Elle évite ainsi de recompter les installations de toutes les machines à chaque
ouverture. Les contrôles d’accès et le périmètre logiciel restent appliqués.
Le décompte des installations reste disponible dans le catalogue et l’inventaire.


## Analyses intégrées aux fiches Dash

`app.business.asset_analysis` construit les analyses à partir des références et
versions du manifeste publié. Il contrôle l’accès à l’espace et son périmètre
avant les lectures. Les produits sont identifiés par `software_id`, jamais par
une recherche approximative sur leur nom.

La fiche produit croise les installations, machines, sites et filiales avec les
résultats Gold par installation. Elle fournit le déploiement par filiale,
l’activité, la distribution des jours actifs et la couverture des observations.
La fréquence utilise uniquement les périodes entièrement observées. Une activité
positive reste prouvée même si certains relevés manquent ; zéro activité avec une
couverture incomplète reste indéterminé. Les graphiques sont consultables sur la
fiche, sans passage obligatoire par Coûts & économies.

La fiche machine lit ses dimensions, installations, utilisateurs reliés et
observations du dernier relevé dans la même publication. Elle croise ces données
avec les jours actifs de la période Gold. Les versions explicites des installations
et les versions des observations sont conservées ; une version absente n’est pas
inventée. Le fonctionnement d’un système est distingué de l’activité applicative.

Ces lectures ne lancent ni collecte ni Spark. Les filtres machine et produit sont
transmis au lecteur Delta. Les graphiques de fréquence sont des distributions
sur la période, pas des courbes journalières reconstituées. En l’absence de cette
publication d’entreprise, l’inventaire reste consultable et l’absence d’analyse
est affichée explicitement.

## Entretien des projections PostgreSQL

Chaque réindexation publie une nouvelle projection. Les anciennes générations
peuvent donc occuper davantage de place que l’index actif. La commande suivante
calcule un plan sans supprimer de données :

```sh
docker compose exec dash nexora lake prune-index
```

L’option `--apply` supprime uniquement les lignes des anciennes projections SQL
qui ne sont plus référencées. Elle conserve l’index actif, les références du journal
de collecte et de reprise, celles des instantanés BI et les métadonnées des
exécutions. Aucun objet du lac n’est supprimé. Une dépendance introuvable,
une collecte en cours ou une sauvegarde tenant le verrou empêche l’opération.
La commande verrouille les tables de publication pendant la vérification.
Cette maintenance est manuelle, elle n’est pas exécutée à chaque publication.

Un `DELETE` libère de la place réutilisable dans PostgreSQL, sans nécessairement
réduire le volume Docker. Pour rendre cette place au système, une maintenance
séparée peut exécuter `VACUUM (FULL, ANALYZE) inventory_entities` sur la base
concernée. Cette réécriture demande de l’espace temporaire et bloque l’accès
à la table pendant son exécution ; prévoir une interruption des lectures.
Ne pas supprimer un volume PostgreSQL ou MinIO utilisé par l’application pour
réaliser cet entretien : ce serait une remise à zéro complète.

Les commandes `nexora dev` exigent l’image de développement : construire celle-ci avec `docker compose -f docker-compose.yml -f docker-compose.dev.yml build dash`. Elles sont absentes de l’image de production.
