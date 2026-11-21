[English](SECURITY_AUDIT.md) · **Français**

# Revue de sécurité avant la 1.0 (jalon 0.26.0)

Une revue faite par les mainteneurs et leur assistant, des surfaces ajoutées depuis la 0.20 et des plus anciennes. **Ce n'est pas un audit indépendant.** [SECURITY.fr.md](SECURITY.fr.md) décrit le modèle ; cette page dit ce qui a été vérifié et ce qui reste ouvert.

## Ce qui a été vérifié

| Surface | Vérification | Résultat |
|---|---|---|
| Routes des machines (`/api/noeud/*`) | Jeton obligatoire (haché en SHA-256 au repos, comparaison à temps constant), un nœud éteint ne reconnaît personne, le jeton n'ouvre rien d'autre que ces routes, corps de demande réduit à une liste de clés permises, deux demandes simultanées au plus | OK, couvert par `test_machines.py` |
| Appairage | Code à 8 chiffres, usage unique, 5 minutes, 3 en attente au plus, limiteur partagé, même message pour un code faux ou périmé | OK |
| Extinction à distance | Éteinte par défaut sur la machine à éteindre, jeton de nœud valide requis, 30 s de délai, annulable, journalisée des deux côtés | OK |
| Commandes système | Les commandes de Lutin lui-même (moteurs, mises à jour, outils du système) sont des listes d'arguments : pas d'`os.system`, d'`eval/exec/pickle` dans `src/` ; la version donnée à `--rollback-to` doit avoir la forme `X.Y.Z`. **Correction (2026-11-11) :** cette ligne disait « pas de `shell=True` ». C'était faux : l'outil `executer` de l'assistant lance dans un shell la commande écrite par le modèle (`outils.lancer_processus`), par conception et après accord — et jusqu'à cette date les « lectures simples » y passaient sans accord et pouvaient être contournées. Elles ne passent plus par un shell ([ADR 0006](adr/0006-approval-free-commands.md)) | OK pour les commandes de Lutin ; corrigé pour les lectures sans accord |
| Accès web de l'assistant | L'adresse contrôlée est l'adresse contactée (une seule résolution, faite par la connexion) ; la cible de chaque redirection est contrôlée avant d'être contactée ; plage CGNAT refusée ([ADR 0008](adr/0008-outbound-web-guard.md)). Avant le 2026-11-11, une redirection atteignait sa cible avant le contrôle | **Corrigé** (`test_net_guard.py`) ; pas d'adresse épinglée derrière un proxy système |
| Actions « décharger / fermer » de la page Santé | Liste fermée d'actions ; ComfyUI n'est fermé que si Lutin l'a lancé | OK |
| Fichiers servis (`/fichier/`, `/lib/`, `/image/`, `/piece/`) | `..` et variantes encodées refusés | OK, `test_parcours_vierge.py` |
| Corps de requêtes | Plafonds (2 Mo de JSON, 8 Mo d'images, 20 Mo de documents) ; un `Content-Length` non numérique vaut « trop gros » ; le JSON doit être un objet | OK |
| Sites tiers et « rebinding » | `Host` / `Origin` vérifiés, jeton de page exigé en lecture au niveau 1 | OK (`test_serveur_securite.py`) |
| Fichiers de données | Un JSON abîmé ou du mauvais type retombe sur les valeurs par défaut (avant la 0.26.0, un `reglages.json` qui n'était pas un objet faisait planter chaque requête) | **Corrigé en 0.26.0** |
| `lutin colibri` (programme d'un tiers) | Ne tourne que sur ta commande explicite ; archive téléchargée uniquement depuis les publications GitHub du projet, **SHA-256 obligatoire** (pas de sommes publiées = refus), la décompression ne peut pas sortir de son dossier (noms avec `..`, liens et fichiers spéciaux refusés), serveur lié à `127.0.0.1` | OK en test ; il **télécharge un script Python d'un tiers et l'exécute quand tu le démarres** : c'est sa nature, lis sa licence et son code si cela compte pour toi |
| Catalogue de moteurs signé | Ed25519, deux clés, altération et champs inconnus refusés | OK |

## Limites connues (non corrigées, dites franchement)

1. **Les mises à jour sont vérifiées (corrigé après la première version de cette page).** `lutin update` télécharge la roue, calcule sa somme SHA-256 et la compare au `SHA256SUMS.txt` publié à côté ; une somme fausse, un fichier absent de la liste ou une roue énorme refusent la mise à jour, et pip installe ensuite ce fichier vérifié. Limite : le fichier des sommes est sur le même hébergeur que la roue, donc cela attrape une corruption ou un fichier échangé, **pas une publication compromise**. Une publication sans `SHA256SUMS.txt` (les anciennes) est acceptée avec un avertissement visible. Essayé pour de vrai sur les publications v0.24.0 et v0.21.0.
2. **HTTP en clair sur le réseau local** (niveaux 2 et 3 sans certificat de proxy, et trafic entre machines) : qui peut lire le réseau lit ce qui y passe. Hors réseau de confiance, utilise le niveau 3 derrière un proxy TLS.
3. **Jeton de nœud et appairage** : une machine appairée peut faire tourner le moteur de celle qui le prête, dans la limite de deux demandes, jusqu'à ce que tu la révoques. Par défaut elle ne peut lire ni conversations, ni fichiers, ni réglages. **Chaque droit facultatif élargit cela (correction du 2026-11-13) :** partager les skills ou la mémoire les lui donne à lire ; « laisser les machines appairées mener des conversations ici » lui permet de faire exécuter des tours entiers sur cette machine, avec ses outils et ses dossiers de travail, **et d'accorder elle-même les actions** (les accords sont demandés à celui qui écrit) — en pratique le droit de modifier des fichiers et de lancer des commandes ici, dans les règles du dossier de travail. Tous sont décochés par défaut et visibles dans l'onglet Machines.
4. **Pas d'audit indépendant**, pas de campagne de fuzzing, pas de test d'intrusion.
5. **Docker** : non testé contre un utilisateur local hostile ; le conteneur ne monte pas le socket Docker.

## Signaler un problème

Voir [SECURITY.fr.md](SECURITY.fr.md).
