[English](VOICESTUDIO.md) · **Français**

# VoiceStudio : donner une voix à Lutin

L'addon **VoiceStudio** relie Lutin à [VoiceStudio](https://github.com/debpalash/voicestudio), une application de voix qui tourne **sur ta machine** (licence AGPL-3.0 ; les modèles de voix ont chacun leur licence, que VoiceStudio affiche). Rien ne part sur internet : Lutin ne joint que `127.0.0.1`.

## Ce que le modèle peut faire

| Outil | Ce qu'il fait | Accord |
|---|---|---|
| `voix_liste` | liste les voix disponibles | non (lecture) |
| `voix_parler` | lit un texte (4096 caractères au plus par appel) avec une voix et crée un fichier audio (WAV, MP3 ou FLAC) joint sous le message | oui, à chaque fois |
| `voix_transcrire` | écrit ce qui se dit dans un enregistrement ou une vidéo du projet | non (lecture) |
| `voix_cloner` | crée une voix à partir d'un enregistrement de référence | **oui, toujours, même avec « accord automatique »** |

## Cloner une voix : seulement avec la permission de la personne

Le clonage demande à chaque fois ton accord, avec une déclaration écrite : « c'est ma voix » ou « la personne a donné sa permission ». Le modèle doit te poser la question, jamais la présumer. La déclaration est aussi transmise à VoiceStudio, qui la garde avec le profil. Une voix clonée sans l'accord de son propriétaire peut servir à tromper : ne le fais pas, et dans beaucoup de pays c'est illégal.

## Mise en route

1. **Lance VoiceStudio** : application de bureau (`bun run dev` dans le dépôt) ou Docker : `docker run -d -p 127.0.0.1:3900:3900 -e OMNIVOICE_API_KEY ghcr.io/debpalash/voicestudio:stable`. Sans carte graphique, il fonctionne sur le processeur, plus lentement.
2. Dans Lutin : **Extensions > VoiceStudio**, règle le port (3900 par défaut) et, **avec l'image Docker**, la clé API (la valeur de `OMNIVOICE_API_KEY`, que VoiceStudio exige même depuis cette machine). Active l'addon : Lutin vérifie que VoiceStudio répond et compte les voix.
3. Demande dans une conversation : « lis ce texte avec la voix de Narrateur », « transcris enregistrement.wav », « clone ma voix à partir de moi.wav ».

Les fichiers audio créés sont rangés dans le dossier de données de Lutin (`addons/voicestudio/audio/`) ; la carte sous le message permet de les écouter, les télécharger ou les supprimer.

## Ce qui n'est pas vérifié

Les tests utilisent un **faux** VoiceStudio. L'application réelle n'a pas été lancée : les routes (`/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/voices`, `/profiles`, `/profiles/{id}/attestation`) viennent de la lecture de son code source et de sa documentation. Si une version future les change, la vérification quotidienne de l'addon passe en « à réparer » au lieu de se taire. À essayer sur ta machine : une lecture, une transcription, un clonage de ta propre voix.
