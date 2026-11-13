# Glossary: French to English

The vocabulary of the migration to English ([ADR 0001](../adr/0001-english-and-clean-break-at-1.0.md)). One French term has one English term, used everywhere:
module names, identifiers, API routes and fields, documentation. A term is added here before it is used in a renaming.

## Domain terms

| French | English | Note |
|---|---|---|
| moteur (de modèles) | engine | Ollama, llama.cpp, LM Studio… what runs a model |
| le moteur de Lutin (`moteur.py`) | core | the agent core and shared state; never « engine », which means the above |
| modèle | model | |
| catalogue | catalog | American spelling throughout |
| réglages | settings | |
| dossier de travail / travaux | workspace / workspaces | the only part of the disk the assistant may read and change |
| accord / approbation | approval | |
| accord automatique | automatic approval | |
| outil | tool | what the model calls |
| programme externe (uv, Node.js) | external program | never « tool », which means the above |
| tour | turn | one user request and everything the agent does to answer it |
| boucle d'agent | agent loop | |
| conversation | conversation | |
| mémoire / notes | memory / notes | |
| fiche de suivi | progress sheet | the file that holds the memory of a very long conversation |
| rappel | recall | keyword search in documents and past conversations |
| recherche par le sens | semantic search | |
| pièce jointe | attachment | |
| fichier produit | produced file | a file created during a conversation |
| appareil (appairé) | (paired) device | a phone or computer signed in with a PIN |
| machine (appairée) / nœud | (paired) machine / node | another Lutin; « node » in the protocol |
| piloter | lead (a conversation) | the right to run turns on another machine |
| niveau d'accès : local, réseau, proxy | access level: local, network, proxy | |
| configurateur | configurator | whoever may change settings from the page |
| hors ligne (strict) | (strict) offline | |
| tâche planifiée | scheduled task | |
| travail de fond | background job | |
| mission | mission | a long task with a plan and checkpoints |
| santé | health | |
| alimentation (réveil, extinction) | power (wake-up, shutdown) | |
| sauvegarde / restauration | backup / restore | |
| reprise (d'un autre assistant) | migrate / import | the CLI command is `migrate` |
| mise à jour | update | |
| banc d'essai | bench | |
| adéquation | fit | does this model fit this machine |
| variante (de précision) | variant (quantization) | |
| réflexion / pensée | thinking | the part of an answer a reasoning model writes before answering |
| observatoire | observatory | what each model turn did, for debugging |
| sorties | outbound | what leaves the machine (queries sent to a search service) |
| zone de notification | (system) tray | |

## Modules (done, 2026-11-13)

Renamed in one mechanical commit; contents unchanged. The package stays flat for now: moving modules into sub-packages is part of the backend step,
when their responsibilities are actually separated.

| Before | After |
|---|---|
| `acces` | `access` |
| `actualites` | `news` |
| `adequation` | `model_fit` |
| `affirmations` | `false_claims` |
| `alimentation` | `power` |
| `apercu` | `page_preview` |
| `bench_moteurs` | `engine_bench` |
| `boucles` | `loop_detection` |
| `calibrage` | `calibration` |
| `catalogue` | `model_catalog` |
| `catalogue_moteurs` | `engine_catalog` |
| `chat_terminal` | `terminal_chat` |
| `compat_modeles` | `model_compat` |
| `conseil` | `performance_advice` |
| `conseil_machine` | `low_end_mode` |
| `decouverte` | `model_discovery` |
| `demarrage` | `startup` |
| `dialogue` | `agent` |
| `docker_aide` | `docker_doctor` |
| `donnees` | `storage` |
| `emplacements` | `locations` |
| `espaces` | `workspace_manager` |
| `essai_moteur` | `engine_trial` |
| `estimation` | `memory_estimate` |
| `exllamav3_catalogue` | `exllamav3_catalog` |
| `extraction` | `text_extraction` |
| `fichiers` | `produced_files` |
| `fond` | `background_jobs` |
| `horsligne` | `offline` |
| `infos_modele` | `model_info` |
| `installation` | `setup_wizard` |
| `lmstudio_catalogue` | `lmstudio_catalog` |
| `machine` | `hardware` |
| `mcp_catalogue` | `mcp_catalog` |
| `mesures_moteurs` | `engine_metrics` |
| `miseajour` | `updates` |
| `moteur` | `core` |
| `moteur_llamacpp` | `llamacpp_engine` |
| `moteur_openai` | `openai_engine` |
| `moteurs` | `engines` |
| `moteurs_docker` | `docker_engines` |
| `moteurs_maj` | `engine_updates` |
| `observatoire` | `observatory` |
| `ollama_partage` | `ollama_shared_models` |
| `outils` | `tools` |
| `outils_externes` | `external_programs` |
| `outils_utiles` | `find_tools` |
| `ouverture` | `open_file` |
| `pensee` | `thinking` |
| `pieces` | `attachments` |
| `plan` | `project_map` |
| `planifie` | `scheduled_tasks` |
| `projet_claude` | `claude_project` |
| `rappel` | `recall` |
| `recherche` | `web_search` |
| `registre_ollama` | `ollama_registry` |
| `reglages_outils` | `tool_settings` |
| `regles` | `message_rules` |
| `remplacement` | `engine_replace` |
| `repondeur` | `auto_reply` |
| `reprise` | `migrate` |
| `ressources_chargees` | `loaded_resources` |
| `revue` | `change_review` |
| `routeur` | `model_router` |
| `sansconsole` | `no_console` |
| `sante` | `health` |
| `sauvegarde` | `backup` |
| `securite` | `security` |
| `selection` | `model_selection` |
| `serveur` | `server` |
| `skills_tiers` | `third_party_skills` |
| `sorties` | `outbound` |
| `suivi` | `progress_sheet` |
| `travaux` | `workspaces` |
| `variantes` | `model_variants` |
| `zone` | `tray` |

Unchanged because already English or a proper name: `addons` and its `addons_*` modules, `archive`, `bench`, `cli`, `client`, `colibri`, `config`, `diagnostic`,
`documents`, `ed25519`, `embeddings`, `exllamav3`, `github`, `i18n`, `images`, `lmstudio`, `machines`, `mcp`, `mcp_demo`, `mission`, `modes`, `net_guard`,
`notifications`, `ollama_client`, `qr`, `safe_commands`, `web`.

Six imports keep the old name as an alias where renaming the name in the file would have collided with another one
(`background_jobs as fond`, `workspaces as travaux`, `storage as donnees`, `tray as zone`): they go with the identifier pass.

## Not renamed yet

Identifiers inside the modules (functions, variables, classes), comments and docstrings, test file names, the catalogues' source language,
the HTTP routes and fields, the stored keys, the environment variables and the tool names the models see: see [PLAN.md](PLAN.md), step 3.
