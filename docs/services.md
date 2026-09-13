# Services Python

Nexora-Dash n’expose pas de contrat REST métier. Les callbacks Dash utilisent directement les fonctions Python suivantes, avec un contexte utilisateur et un espace validés.

| Module | Responsabilité |
| --- | --- |
| `app.business.workspace_service` | Authentification, espaces, membres, coûts, dossiers et notes |
| `app.business.portfolio_service` | Catalogue et périmètre logiciel |
| `app.business.inventory_service` | Inventaire paginé et installations |
| `app.business.asset_analysis` | Croisements Delta et distributions intégrées aux fiches produit et machine |
| `app.business.exploration` | Agrégations croisées et qualité des dimensions |
| `app.business.settings_service` | Paramètres d’analyse partagés |
| `app.services.published_analytics` | Lecture des résultats Gold publiés |
| `app.bi.reader_service` | Lecture contrôlée de publications BI |

Les services appliquent les rôles, les périmètres et les versions attendues lors des modifications. `BusinessError` véhicule une erreur métier jusqu’à l’affichage. Les nombres utilisés pour ses catégories ne constituent pas des endpoints HTTP.

Dash utilise son propre transport HTTP pour servir l’interface et ses callbacks. Ce transport n’est pas une seconde API REST destinée à la consommation des données métier.

Les exports BI sont préparés séparément et restreints à leur audience. L’ancien accès REST BI n’est plus disponible ; la livraison des exports et la connexion Power BI cible restent à finaliser.
