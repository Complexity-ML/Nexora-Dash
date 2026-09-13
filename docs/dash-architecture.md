# Interface Dash/Plotly

`nexora/app/dash_ui/` regroupe :

- `app.py` : application, session, navigation et callbacks.
- `context.py` : utilisateur, espace et services accessibles.
- `actions.py` : commandes métier autorisées.
- `components.py` : cartes, tableaux, champs et graphiques.
- `pages/` : vues analytiques et fonctions métier.
- `assets/nexora.css` : thème et mise en page responsive.

Les URL de navigation utilisent un fragment (`#/inventory`, `#/explore`, etc.). Elles sélectionnent une page et des filtres ; elles ne correspondent pas à des endpoints REST. Les traitements Spark sont autonomes et les callbacks lisent les publications disponibles.

Les formulaires utilisent des identifiants de champs explicites. Les parcours « compte existant » et « nouveau compte » possèdent leurs propres champs pour éviter toute attribution involontaire de rôle ou d’adresse.

Les tests `test_dash.py` vérifient les sessions, les contrôles d’accès et des commandes via le transport réel des callbacks Dash. `verify_dash_pages.py` vérifie la construction des pages sur la démonstration configurée ; il ne remplace pas la validation visuelle.
