# Architecture Nexora-Dash

Nexora est une application analytique Python. DIGIMON expose l’API REST consommée par le collecteur Nexora. Le navigateur utilise Dash ; les callbacks appellent directement les services Python.

```text
Agents et Beacon → DIGIMON
                      ↓
              Collecteur Python
                      ↓
       Réception conservée / journal PostgreSQL
                      ↓
         Validation et tables Silver Delta
                      ↓
             Traitements PySpark
                      ↓
       Publication Gold atomique et versionnée
                      ↓
           Services Python → Dash/Plotly
```

La collecte et la reprise s’exécutent indépendamment de l’interface. Une lecture dans Dash ne doit ni collecter DIGIMON ni déclencher Spark. Les résultats sont lus à une version publiée ; les tables d’une même collection restent liées par son manifeste.

PostgreSQL conserve les sessions, espaces, rôles, coûts, dossiers, notes et le journal de collecte. Les index d’inventaire servent les recherches et agrégations paginées. MinIO conserve les données du lac. Les vues de qualité consultent les dimensions disponibles ; elles ne prétendent pas détecter automatiquement tous les types de données ou toutes les données personnelles.

Les droits métier sont vérifiés dans les services à chaque commande. Les filtres du navigateur ne constituent pas une autorisation. Les installations, utilisateurs nommés, cœurs et capacités simultanées restent des unités distinctes.

## Intégration DIGIMON

Nexora reste déployable indépendamment. Son exposition sous une route de DIGIMON nécessite un accord sur le reverse proxy et l’authentification. Cette intégration n’est pas validée par la démonstration locale. Aucun accès direct au Beacon ou aux agents n’est nécessaire.
