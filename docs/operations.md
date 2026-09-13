# Exploitation et industrialisation

## État du MVP

- FastAPI et Spark partagent actuellement le même conteneur backend.
- Spark s'exécute en `local[*]` dans la démo.
- MinIO fournit l'API S3 locale.
- delta-rs résout une version Delta et transmet les capacités à Spark via Arrow.
- Le résultat Gold courant est écrit dans la table Delta `gold/analytics/latest`.

Ces choix réduisent le coût de démarrage mais les interfaces (`DigimonConnector`, `ObjectStore`, modèles canoniques) permettent une évolution indépendante.

## Trajectoire de production

1. Remplacer les identifiants MinIO locaux par un gestionnaire de secrets.
2. Utiliser un bucket et des préfixes par environnement avec chiffrement, versionnement et politique de rétention.
3. Exécuter les synchronisations via un ordonnanceur plutôt que via le seul endpoint manuel.
4. Déployer Spark sur le cluster cible et configurer S3A pour lire Silver directement.
5. Versionner les datasets Gold et publier atomiquement un pointeur vers la dernière version valide.
6. Mettre en cache ou servir Gold sans relancer Spark à chaque lecture API.
7. Ajouter authentification, autorisation par entité, rate limiting et journal d'audit à FastAPI.
8. Générer le client TypeScript depuis OpenAPI dans la CI.

## Sécurité

- Restreindre `CORS_ORIGINS` aux origines HTTPS de production.
- Ne jamais utiliser les credentials `minioadmin` hors poste de développement.
- Placer DIGIMON et S3 sur un réseau serveur non accessible au navigateur.
- Filtrer ou chiffrer les identifiants utilisateur et machine selon la politique de données.
- Définir une durée de rétention Bronze, potentiellement plus sensible que Silver et Gold.
- Protéger `POST /sync` par une permission opérationnelle.

## Observabilité recommandée

Mesures minimales :

- date et résultat de la dernière synchronisation ;
- nombre de lignes Bronze/Silver écrites ;
- durée, volume lu et résultat du job Spark ;
- fraîcheur du dernier dataset Gold ;
- erreurs DIGIMON, S3 et Spark par catégorie ;
- nombre de pools rejetés lors du mapping canonique.

Les logs doivent contenir un identifiant de snapshot, jamais un credential ni un payload utilisateur complet.

## Résilience et qualité

- Rendre les écritures idempotentes avec un identifiant de snapshot source stable lorsque DIGIMON le fournit.
- Contrôler le schéma, les valeurs négatives, doublons et timestamps futurs avant Silver.
- Ne publier Gold qu'après validation complète du job.
- Tester les restaurations et la lecture de partitions anciennes.
- Ajouter des seuils d'alerte sur la fraîcheur, sans confondre absence de données et consommation nulle.

## Limites analytiques

La saturation actuelle est une projection linéaire déterministe, non un modèle prédictif. Le potentiel de récupération dépend d'un seuil et d'une réserve configurables. Avant tout usage contractuel, intégrer les coûts, règles éditeur, saisonnalité, réservations, profils d'accès et validations métier.

## Migration et test à vide

`python -m scripts.verify_fresh_delta` génère un an de démo dans un préfixe MinIO vide et vérifie les analyses, la persistance Gold et l’absence de fichiers Silver historiques. Il ne change pas le jeu actif.

`python -m scripts.migrate_enterprise_delta` prépare les tables de l’inventaire existant et compare leur contenu sans les activer. `--resume-root` reprend un préfixe de migration interrompu. Les producteurs doivent être arrêtés pour la bascule finale.

La politique de compaction, de schéma et de rétention est décrite dans [Delta Lake](delta-lake.md). Aucune purge automatique n’est activée.
