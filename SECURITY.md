# Signaler une faille de sécurité

Ne crée pas d'*issue* publique pour une faille. Utilise l'onglet **Security > Report a vulnerability** du dépôt GitHub (signalement privé), ou écris au mainteneur (adresse à renseigner à la publication du dépôt).

Donne : la version (`lutin --version`), le niveau de sécurité utilisé, ce que tu as fait et ce que tu as obtenu. Un rapport `lutin doctor` est utile et ne contient aucune conversation.

Tu auras un accusé de réception sous 7 jours. Les failles confirmées sont corrigées avant d'être décrites publiquement.

Ce qui est considéré comme une faille : accès sans authentification aux niveaux 2 et 3, contournement du contrôle `Host` / `Origin`, lecture ou écriture hors du dossier de travail, exécution de commande sans accord, fuite du jeton ou des sessions. Voir [docs/SECURITE.md](docs/SECURITE.md) pour le modèle de menace.
