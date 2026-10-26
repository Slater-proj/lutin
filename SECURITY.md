# Reporting a security vulnerability · Signaler une faille de sécurité

## English

Do not open a public issue for a vulnerability. Use the **Security > Report a vulnerability** tab of the GitHub repository (private report).

Give: the version (`lutin --version`), the security level used, what you did and what you got. A `lutin doctor` report is useful and contains no conversation.

You will get an acknowledgement within 7 days. Confirmed vulnerabilities are fixed before being described publicly.

What counts as a vulnerability: access without authentication at levels 2 and 3, bypass of the `Host` / `Origin` check, reading or writing outside the workspace folder, running a command without approval, leak of the token or the sessions. See [docs/SECURITY.md](docs/SECURITY.md) for the threat model.

## Français

Ne crée pas d'*issue* publique pour une faille. Utilise l'onglet **Security > Report a vulnerability** du dépôt GitHub (signalement privé).

Donne : la version (`lutin --version`), le niveau de sécurité utilisé, ce que tu as fait et ce que tu as obtenu. Un rapport `lutin doctor` est utile et ne contient aucune conversation.

Tu auras un accusé de réception sous 7 jours. Les failles confirmées sont corrigées avant d'être décrites publiquement.

Ce qui est considéré comme une faille : accès sans authentification aux niveaux 2 et 3, contournement du contrôle `Host` / `Origin`, lecture ou écriture hors du dossier de travail, exécution de commande sans accord, fuite du jeton ou des sessions. Voir [docs/SECURITY.fr.md](docs/SECURITY.fr.md) pour le modèle de menace.
