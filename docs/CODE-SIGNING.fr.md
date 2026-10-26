[English](CODE-SIGNING.md) · **Français**

# Politique de signature du code

L'installateur Windows (`lutin-setup-*.exe`) est construit par GitHub Actions à partir de ce dépôt, depuis le seul code public, par le workflow `.github/workflows/release.yml`. La signature est **en cours de demande** auprès de la SignPath Foundation (gratuite pour l'open source) ; tant qu'elle n'est pas approuvée l'installateur **n'est pas signé** et Windows SmartScreen peut avertir. La somme de contrôle de chaque version est dans `SHA256SUMS.txt`.

Quand la signature sera active :

- **Seuls les fichiers construits par le workflow de ce dépôt** sont signés, depuis un commit de `main` (construction vérifiable : SignPath contrôle l'origine du fichier).
- **Rôles** : Slater-proj (propriétaire) est auteur, relecteur et approbateur. Chaque demande de signature est **approuvée à la main** avant que le fichier soit signé. Les contributions des autres sont relues par le propriétaire avant d'être fusionnées.
- **L'authentification à deux facteurs** est exigée sur le compte GitHub et sur SignPath.
- **Vie privée** : voir [PRIVACY.fr.md](PRIVACY.fr.md). Lutin n'envoie aucune information sur toi ; les contacts qu'il peut faire y sont listés.
- L'installateur s'installe pour l'utilisateur (sans droits administrateur), demande avant de modifier le PATH, et se désinstalle depuis les applications installées de Windows.
- Nom du produit `Lutin`, version du produit = la version publiée.

Mise en place (pour le mainteneur) : [PUBLISHING.fr.md](PUBLISHING.fr.md), « Signer l'installateur Windows ».
