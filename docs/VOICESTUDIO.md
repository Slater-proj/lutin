**English** · [Français](VOICESTUDIO.fr.md)

# VoiceStudio: giving Lutin a voice

The **VoiceStudio** addon connects Lutin to [VoiceStudio](https://github.com/debpalash/voicestudio), a voice application that runs **on your machine** (AGPL-3.0 licence; each voice model has its own licence, which VoiceStudio shows). Nothing goes to the internet: Lutin only reaches `127.0.0.1`.

## What the model can do

| Tool | What it does | Agreement |
|---|---|---|
| `voix_liste` | lists the available voices | no (read-only) |
| `voix_parler` | reads a text (4096 characters at most per call) with a voice and creates an audio file (WAV, MP3 or FLAC) attached under the message | yes, every time |
| `voix_transcrire` | writes down what is said in a recording or a video of the project | no (read-only) |
| `voix_cloner` | creates a voice from a reference recording | **yes, always, even with "automatic agreement"** |

## Cloning a voice: only with the person's permission

Cloning asks for your agreement every time, with a written statement: "it is my voice" or "the person gave their permission". The model must ask you, never assume. The statement is also sent to VoiceStudio, which keeps it with the profile. A voice cloned without its owner's agreement can be used to deceive: don't, and in many countries it is illegal.

## Getting started

1. **Start VoiceStudio**: desktop app (`bun run dev` in the repository) or Docker: `docker run -d -p 127.0.0.1:3900:3900 -e OMNIVOICE_API_KEY ghcr.io/debpalash/voicestudio:stable`. Without a graphics card it works on the processor, more slowly.
2. In Lutin: **Extensions > VoiceStudio**, set the port (3900 by default) and, **with the Docker image**, the API key (the value of `OMNIVOICE_API_KEY`, which VoiceStudio requires even from this machine). Enable the addon: Lutin checks that VoiceStudio answers and counts the voices.
3. Ask in a conversation: "read this text with the voice of Narrator", "transcribe recording.wav", "clone my voice from me.wav".

The audio files created are stored in Lutin's data folder (`addons/voicestudio/audio/`); the card under the message lets you listen, download or delete them.

## What is not verified

The tests use a **fake** VoiceStudio. The real application has not been run: the routes (`/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/voices`, `/profiles`, `/profiles/{id}/attestation`) come from reading its source code and documentation. If a future version changes them, the addon's daily check turns "to repair" instead of staying silent. To try on your machine: one reading, one transcription, one cloning of your own voice.
