# Parcours de la démonstration SAM

Lancer la stack suivant le [workflow](../WORKFLOW.md), puis ouvrir
http://localhost:5173. Les routes à fragment permettent les liens directs et le
rechargement. Les données de licences sont explicitement fictives ; les actions
métier sont persistées sur le serveur.

| Route | Parcours |
| --- | --- |
| `#/overview` | Synthèse du périmètre, graphique, notifications |
| `#/portfolio` | Sélection des logiciels pris en charge par l’espace |
| `#/software` | Catalogue filtré et recherche |
| `#/software/:poolId` | Usage, capacité, risque et ouverture d’un dossier |
| `#/analysis` | Comparaison de périodes, variations mensuelles et capacités |
| `#/licenses` | Stock fourni par la source |
| `#/flexlm` | Risques et projections par pool |
| `#/savings` | Coûts partagés et estimations annuelles |
| `#/cases` | Dossiers, assignations, commentaires et justificatifs |
| `#/sources` | Source active et collecte |
| `#/pipelines` | État des étapes et recalcul |
| `#/lake` | Inventaire des objets Bronze, Silver et Gold |
| `#/settings` | Profil, membres, création de comptes et seuils d’analyse |
| `#/help` | Guide et limites des analyses |

La recherche se lance avec Entrée. Les menus d’espace distinguent les membres
et accès du portefeuille de licences. Lorsque tout le catalogue est suivi,
décocher un logiciel passe en sélection personnalisée ; enregistrer applique
le nouveau périmètre. Les dossiers et coûts historiques sont conservés.

## Partage et droits

PostgreSQL conserve comptes, espaces, appartenances, coûts, dossiers,
commentaires et événements. MinIO conserve les tables Delta et résultats
analytiques. Le navigateur ne conserve que des préférences d’affichage et la
session ; une importation explicite peut reprendre d’anciens coûts locaux.

Le lecteur consulte. L’analyste modifie coûts et dossiers. L’administrateur de
l’espace gère aussi les membres et le portefeuille. Il peut créer un compte avec
un mot de passe de 16 caractères minimum ou ajouter un compte existant.
L’opération ne remplace jamais le mot de passe d’un compte existant et n’envoie
aucun e-mail. Un nouveau compte reçoit uniquement l’appartenance choisie.
Les administrateurs de Nexora Groupe gèrent les mutations du lac commun et
les seuils globaux.

Les API vérifient les appartenances et les rôles. Le catalogue source global
est volontairement commun aux utilisateurs connectés pour choisir librement
leurs logiciels ; les données métier des espaces restent isolées. Retirer un
membre ou le passer lecteur supprime ses assignations avec historique. Les
modifications concurrentes des dossiers et coûts sont contrôlées par version.

## Dossiers et analyses

Le parcours courant est À examiner → En cours → Terminé. Un responsable peut
être assigné ; une note explique les changements. La clôture indique une quantité
de licences récupérées déclarée ou Aucune suite. La réouverture conserve le
résultat précédent dans les événements serveur. Les anciennes références
administratives restent disponibles, mais ne sont plus requises dans le formulaire.

Le journal et l’export présentent les notes actuelles. Supprimer une note efface
son texte initial et toutes ses versions modifiées du stockage serveur. Seules
les métadonnées de suppression subsistent ; l’historique des décisions du dossier
est conservé. La migration nettoie aussi les notes déjà supprimées.

Une estimation de récupération ne constitue pas une économie contractuelle.
Les tarifs sont saisis ; le connecteur ne fournit pas les règles contractuelles.
La saturation est une extrapolation linéaire indicative. Une année décrit des
variations mensuelles, mais ne démontre pas une saisonnalité récurrente.
Les jours absents ne sont pas inventés. Les changements de capacité après une
lacune portent une incertitude sur leur date effective.

## Reproductibilité et limites

Le rejeu annuel contrôlé est documenté dans [WORKFLOW.md](../WORKFLOW.md).
Ses outils sont masqués et leurs API refusées par défaut :
`DEMO_TOOLS_ENABLED=false`. Leur activation explicite requiert également une
source fictive et un administrateur du lac. Le rejeu prépare une génération
isolée, valide ses scénarios avec Spark puis l’active sans effacer les données
métier ni les anciennes générations.

Il n’y a pas encore de SSO, de récupération de mot de passe par e-mail,
d’ordonnanceur ni de surveillance permanente. Le contrat DIGIMON réel reste
à adapter et n’est pas requis pour cette démonstration. L’archivage des anciennes
générations ne comporte pas de nettoyage automatique.

## Vérification

Les commandes de tests Docker/PostgreSQL, Spark et frontend figurent dans
[WORKFLOW.md](../WORKFLOW.md). Les tests backend vérifient droits, isolation,
historique, versions concurrentes et scénarios du lac. Les tests frontend
vérifient notamment périodes, agrégations et transport.

Les derniers changements visuels sont compilés et déployés localement ; les
parcours navigateur complets n’ont pas été rejoués automatiquement, conformément
à la demande de ne plus piloter le navigateur. Cette vérification reste distincte
des tests API.
