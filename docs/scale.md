# Dimensionnement du parc

Le parc cible annoncé dépasse 100 000 licences. Ce nombre n’est pas un nombre
de lignes : avec un relevé par licence et par jour, 100 000 licences représenteraient
36 500 000 relevés par an. Des totaux par pool ou des événements individuels
produisent des volumes très différents. La granularité reste à confirmer avec
l’équipe DIGIMON.

DIGIMON remonte aussi des machines, VM et usages, selon les informations du
porteur du projet. SAM propose désormais un modèle fictif de filiales, sites, utilisateurs, machines
et observations logiciel–machine–utilisateur. Son mapping réel doit être confirmé
avec un échantillon DIGIMON.
Leur nombre et leur granularité ne doivent pas être déduits du nombre de licences.

## Ce que valide le prototype

Le jeu de référence des capacités contient 12 pools et 4 380 relevés journaliers.
Le scénario d’entreprise ajoute des dimensions d’inventaire et des observations
par installation, dans des partitions Delta quotidiennes. Sa génération et
son activation locales ont été vérifiées ; elles ne constituent pas un test
de charge concurrente ni une validation du réseau de production.

Python permet ici d’utiliser PySpark pour les agrégations. Le moteur Spark peut
exécuter des traitements distribués ; l’utilisation de Python ne suffit pas à
rendre toute l’application distribuée. DIGIMON peut fournir les relevés depuis
son backend Node.js via un contrat API adapté.

## Limites observées dans le code

- `SamPipeline._compute_analytics` télécharge toutes les partitions Silver dans
  un répertoire temporaire du serveur avant le calcul : le disque et les transferts
  de ce serveur bornent actuellement la capacité de traitement.
- `SparkAnalytics.compute_frame` collecte les agrégats par pool et par jour dans
  le processus pilote. Il ne collecte pas chaque observation brute, mais la taille
  des résultats augmente avec le nombre de pools et la durée de l’historique.
- La réponse de synthèse contient les séries journalières du périmètre. Le frontend
  effectue ensuite les comparaisons de périodes. Les réponses devront être bornées
  et les agrégations déportées côté serveur pour des périmètres très importants.
- Le cache évite les recalculs lorsque les données ne changent pas ; il ne supprime
  pas ces limites lors d’un recalcul. La compression réduit les transferts, pas le
  nombre d’objets que le navigateur traite.

## Validation requise avant montée en charge

1. Définir le relevé source, sa clé stable, la fréquence, les corrections et la
   conservation attendue avec l’équipe DIGIMON.
2. Générer un jeu représentatif isolé du jeu de démonstration, avec les mêmes
   colonnes, distributions et cardinalités que la source prévue.
3. Mesurer les transferts, les temps de calcul, la mémoire du pilote, les tailles
   de réponses et le chargement UI, en distinguant cache chaud et recalcul.
4. Adapter la lecture du stockage pour les exécutants Spark, le partitionnement
   et les endpoints agrégés selon ces mesures ; revérifier les résultats métier.

L’architecture cible retient un backend Nexora indépendant pour isoler les
traitements et leur cycle de déploiement. Il consomme uniquement l’API REST du
backend DIGIMON. Les ressources et l’exploitation restent à dimensionner ; le
frontend Nexora est destiné à une route dédiée dans DIGIMON.

Le scénario d’entreprise v7 conserve 92,345 millions d’observations fictives sur
365 jours, 110 000 salariés et 16 500 prestataires, ainsi que 138 500 machines
dont 20 000 VM, réparties sur 180 sites. Les dimensions
sont partagées entre partitions et les observations sont quotidiennes. Ce volume
est une hypothèse de démonstration, pas une mesure de DIGIMON.

L’index de consultation PostgreSQL évite de relire tout le snapshot à chaque clic.
Une mesure antérieure, sur la génération de 122 000 machines : la recherche locale IIS a retourné 6 666 résultats, dont
25 transférés en environ 16 Ko, en 0,114 seconde pour la requête d’index.
Cette mesure exclut le réseau navigateur et ne prouve pas la tenue en production.
Voir [le modèle d’inventaire](inventory.md) pour la génération et ses limites.

L’extension `product-usage-v1` ajoute 241 082 500 observations synthétiques
(660 500 par jour sur 365 jours) pour les produits hors pools. Le rapport combiné
couvre 30 produits et 912 500 installations. Elle distingue le fonctionnement
des systèmes, l’activité des services et l’exécution des applications. Les
dimensions ne sont pas recopiées dans chaque partition quotidienne.

La construction du pipeline n’initialise plus Spark : il démarre uniquement
lors d’un calcul qui le nécessite. Après déploiement local, les requêtes HTTP
catalogue, périmètre et rapport d’installations ont pris respectivement
78 ms, 11 ms et 29 ms. Ces mesures ponctuelles, avec résultats Gold disponibles,
ne sont ni un percentile de latence ni une garantie sous charge.

## Lecture du catalogue indexé

La liste des logiciels utilise un résumé par `inventory_run`, construit dans la
même transaction que la publication de l’index. Elle ne redéploie plus les
produits des machines à chaque requête. Les produits restent identifiés par leur
`software_id` ; les périmètres partiels filtrent les identifiants de pool ou de
produit. Les index anciens sans résumé conservent le calcul de secours.

Après migration, `python -m scripts.rebuild_software_summary` depuis `backend/`
reconstruit le résumé de l’index courant sans changer son pointeur. Les prochains
index produisent automatiquement leur résumé.

`python -m scripts.benchmark_local_reads --workspace demo --repeats 4 --concurrency 4`
mesure les routes locales d’inventaire, de logiciels et d’usages. La commande est
limitée aux hôtes locaux, n’effectue que des lectures métier et ferme sa session.
La première observation n’est pas présentée comme un véritable démarrage à froid.

Sur la démonstration de 138 500 machines, la médiane de quatre lectures concurrentes
du catalogue est passée d’environ 5,74 s à 0,12 s après matérialisation des comptes.
Les deux mesures ont renvoyé 100 482 octets et aucune erreur. Cet échantillon court
sur le Mac local ne constitue pas un test de charge du réseau Safran ni une mesure
du temps de rendu complet dans le navigateur.

## Lectures simultanées de plusieurs vues

L’option `--mixed` entrelace les requêtes d’inventaire, de catalogue et d’usages,
sous une limite de concurrence commune :

```sh
python -m scripts.benchmark_local_reads --workspace demo --repeats 20 --concurrency 8 --mixed
```

La mesure locale sur le parc de démonstration a donné, après une première lecture
de chaque route, 20 échantillons par route et aucune erreur sur les 60 lectures :

| Route | Médiane | p95 | Taille de réponse décodée |
| --- | ---: | ---: | ---: |
| Machines, première page de 25 | 572 ms | 772 ms | 36 820 octets |
| Catalogue logiciel | 110 ms | 139 ms | 100 482 octets |
| Rapport d’usages des installations | 64 ms | 93 ms | 7 750 octets |

Les latences sont mesurées après acquisition d’une place dans la limite de
concurrence ; elles n’incluent pas la file d’attente du générateur. Les tailles
sont celles des corps décodés par HTTPX, pas les octets compressés sur le réseau.
Le test utilise une session de démonstration, pas huit utilisateurs distincts.
Il ne mesure pas un recalcul Spark, un démarrage à froid, le rendu React ou le
réseau Safran. Les mesures de charge de production restent à effectuer sur
l’environnement cible avec des sessions et périmètres représentatifs.
