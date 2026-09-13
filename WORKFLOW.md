# Développer Nexora-Dash

- `nexora/app/dash_ui/` : pages, composants, styles et callbacks Dash.
- `nexora/app/business/` : services et contrôles d’accès métier.
- `nexora/app/collection/` : journal et reprise des collectes.
- `nexora/tests/` : tests Python et scénarios métier.

Les callbacks appellent directement les services Python. Les traitements Spark s’exécutent indépendamment de la navigation. Les lectures analytiques utilisent une publication du lac validée.

Avant livraison : exécuter les tests sur une base isolée, vérifier les parcours dans le navigateur, construire l’image Docker et relire les changements. Ne pas inclure de secrets, de données locales ou de présentations personnelles dans Git.

La documentation détaillée héritée est en cours de migration ; le README décrit l’architecture actuelle.
