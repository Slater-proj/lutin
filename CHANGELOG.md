# Changelog

Les versions suivantes sont publiées automatiquement (notes générées sur la page des Releases) ; ce fichier garde l'histoire de la première version.

## 0.1.0 (première publication)

Première version : extraite de l'assistant d'un projet personnel, rendue indépendante.

- Détection de la machine (NVIDIA, AMD, Intel, Apple ; RAM ; disques) et sélection de modèles par rôle selon la mémoire disponible.
- Catalogue de modèles en données, validé, avec une phrase de description par modèle.
- Trois niveaux d'accès : cette machine, réseau local (code PIN), proxy (identité du proxy de confiance).
- Installation guidée (`lutin setup`), interactive ou automatique (`--oui`).
- Ligne de commande : `lutin`, `chat`, `modeles`, `pin`, `appareils`, `securite`, `doctor`.
- Vérification des mises à jour de modèles au lancement (au plus une fois par jour, jamais bloquante).
- Scripts d'installation Windows (PowerShell) et Linux / macOS (shell).
- Installation idempotente : relancer le script ou `lutin setup` sur une machine déjà installée ne change rien (ou met à jour si une version plus récente existe) ; les modèles déjà téléchargés ne sont jamais retéléchargés.
- `lutin update` ; boutons « Chercher les mises à jour » et « Chercher de nouveaux modèles » dans l'onglet Modèles ; relance automatique du serveur après une erreur (`lutin serve`).
- Linux et macOS : lectures sans accord (`ls`, `cat`, `pwd`, `which`), refus des chemins absolus, arrêt des commandes avec leurs sous-processus.
- **Mode hors ligne strict** : aucune connexion vers Internet, vérifiée sur les connexions réelles.
- **Dossiers de travail multiples** : un dossier actif à la fois, chaque conversation garde le sien ; ajout réservé à cette machine.
- **Banc d'essai** des modèles sur la machine (vitesse, appel d'outils, code, français, consignes), exportable.
- **Journal des actions** (fichiers modifiés, commandes lancées, accord, personne), **sauvegarde et restauration** des données en un `.zip`.
- **Image Docker** (Lutin + Ollama, GPU NVIDIA en option) et `docker-compose.yml`.
- **Publications automatiques** : fusion dans `main` = version + étiquette + Release + image ; autre branche = candidate sans étiquette.
- Logo, bannière, captures d'écran ; icônes du téléphone aux couleurs de Lutin ; liens directs `/#modeles`, `/#conv=…`.
- Page : pastille verte « réponse terminée, pas lue », réponse qui reste dans sa conversation quand on en ouvre une autre, resynchronisation automatique, liste de tâches qui se ferme quand tout est fait.
