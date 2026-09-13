# Parcours de la démonstration Nexora-Dash

Suivre le [guide de développement](development.md), puis ouvrir http://localhost:8050. Les données du scénario sont fictives ; les modifications métier sont persistées dans PostgreSQL.

| Navigation | Parcours |
| --- | --- |
| `#/overview` | Compteurs du parc, répartitions et historique des capacités |
| `#/explore` | Croisements des dimensions, sélection graphique et détail paginé |
| `#/inventory` | Machines, utilisateurs et sites ; graphiques filtrés et fiches |
| `#/software` | Catalogue des applications, systèmes et services |
| `#/software?product=identifiant` | Fiche d’un produit inventorié |
| `#/annual` | Comparaison de périodes, carte de chaleur et profil mensuel |
| `#/licenses` | Quantités reçues, comparaison par unité et détails par filiale |
| `#/flexlm` | Pression et projection des pools concurrents |
| `#/savings` | Activité des installations ; onglet des capacités et coûts |
| `#/cases` | Dossiers, hypothèses, assignations, notes et export imprimable |
| `#/quality` | Présence des dimensions d’inventaire |
| `#/lake` | Métadonnées des publications et tables disponibles |
| `#/portfolio` | Périmètre logiciel partagé de l’espace |
| `#/settings` | Profil, espaces, membres, comptes et seuils |
| `#/help` | Principes de lecture et limites |

## Lire et approfondir

Un clic sur une barre ou une portion de graphique ouvre les éléments correspondants lorsque le graphique propose cet approfondissement. Par exemple, sélectionner VM ouvre les machines virtuelles de la sélection. Les filtres et le périmètre de l’espace restent contrôlés côté Python.

Les tableaux servent à lire les valeurs et les fiches. La liste des licences est paginée ; les détails par filiale s’ouvrent séparément. Les journées manquantes restent vides dans la carte de chaleur ; elles ne sont pas transformées en consommation nulle.

## Travailler en équipe

Le lecteur consulte. L’analyste gère coûts, dossiers et notes selon les règles métier. L’administrateur de l’espace gère aussi les membres et le périmètre. Les modifications utilisent des versions attendues pour détecter les conflits.

L’ajout d’un compte existant et la création d’un nouveau compte possèdent des formulaires distincts. Un utilisateur sans espace accessible peut créer son premier espace ou se déconnecter. Aucun e-mail n’est envoyé automatiquement.

Les notes supprimées ne réapparaissent pas dans l’export. Le téléchargement d’un dossier revérifie les droits de l’utilisateur ; l’accès à une ancienne page ne suffit pas à conserver ce droit.

## Interpréter les résultats

Une installation n’équivaut pas automatiquement à une licence. Les droits par utilisateur, appareil, cœur ou usage simultané sont présentés dans leur unité. Une absence de donnée ne signifie pas zéro.

Les montants sont des hypothèses à examiner ; ils ne prouvent pas des gains réalisés. Une activité faible ou absente ne suffit pas à décider un retrait. Les règles contractuelles et le périmètre des observations doivent être vérifiés.

## Limites et validation

Les pages lisent les données et résultats publiés ; elles ne lancent pas Spark à chaque interaction. Sans Gold, l’inventaire reste consultable. La collecte DIGIMON est un processus indépendant.

Le contrat réel DIGIMON, son intégration au portail et la connexion Power BI sur le réseau cible ne sont pas validés par la démonstration. Voir [l’état de migration](migration-dash.md) pour les contrôles réalisés et les points encore ouverts.

## Exports CSV

Le parc logiciel et les licences proposent « Exporter CSV ». Le fichier contient tous les résultats de la recherche dans l’espace actif, au-delà de la page affichée. Pour les licences, chaque filiale et chaque unité conserve sa ligne. Le choix d’unité du graphique ne filtre pas le tableau ni son export. Une remontée manquante reste vide avec son état explicite ; elle ne devient pas zéro.

Le téléchargement revérifie la session et l’accès à l’espace. Il appelle les services Python sans lancer Spark. Le CSV utilise un séparateur point-virgule et UTF-8 avec BOM. Les textes pouvant être interprétés comme des formules sont neutralisés pour leur ouverture dans un tableur.
