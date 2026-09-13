# Documentation SAM Analytics

Ce dossier complète le guide de démarrage de la racine. Il décrit l'architecture réellement implémentée, ses limites MVP et les points d'extension prévus.

## Parcours recommandé

1. [Architecture et flux de données](architecture.md) — responsabilités, modèle canonique et parcours Bronze/Silver/Gold.
2. [Développement local](development.md) — lancement Docker ou manuel, configuration et commandes de contrôle.
3. [Services Python](services.md) — services métier appelés directement par Dash.
4. [Intégration DIGIMON](digimon-integration.md) — emplacement exact où adapter le contrat Node.js inconnu.
5. [Exploitation](operations.md) — stockage, sécurité, observabilité et passage vers une plateforme distribuée.

6. [Industrialisation et reprise](industrialisation.md) — journal de collecte, publication atomique, restauration et critères de validation.

## Principes non négociables

- DIGIMON est une **source opérationnelle**, jamais une dépendance du navigateur.
- Les modèles Pydantic de `nexora/app/models/canonical.py` sont la source de vérité.
- Bronze conserve les payloads archivés ; Silver et Gold utilisent des tables Delta sur MinIO, via une interface S3-compatible.
- PySpark est le moteur analytique du MVP ; `local[*]` est un mode de déploiement, pas une contrainte d'architecture.
- Une licence « récupérable » est un élément à examiner, pas une instruction de suppression.
- Aucun secret de source ou de stockage ne doit être envoyé au navigateur.
