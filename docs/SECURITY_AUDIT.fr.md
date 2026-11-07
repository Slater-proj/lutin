[English](SECURITY_AUDIT.md) · **Français**

# Revue de sécurité avant la 1.0 (jalon 0.26.0)

Une revue faite par les mainteneurs et leur assistant, des surfaces ajoutées depuis la 0.20 et des plus anciennes. **Ce n'est pas un audit indépendant.** [SECURITY.fr.md](SECURITY.fr.md) décrit le modèle ; cette page dit ce qui a été vérifié et ce qui reste ouvert.

## Ce qui a été vérifié

| Surface | Vérification | Résultat |
|---|---|---|
| Routes des machines (`/api/noeud/*`) | Jeton obligatoire (haché en SHA-256 au repos, comparaison à temps constant), un nœud éteint ne reconnaît personne, le jeton n'ouvre rien d'autre que ces routes, corps de demande réduit à une liste de clés permises, deux demandes simultanées au plus | OK, couvert par `test_machines.py` |
| Appairage | Code à 8 chiffres, usage unique, 5 minutes, 3 en attente au plus, limiteur partagé, même message pour un code faux ou périmé | OK |
| Extinction à distance | Éteinte par défaut sur la machine à éteindre, jeton de nœud valide requis, 30 s de délai, annulable, journalisée des deux côtés | OK |
| Commandes système | Pas de `shell=True`, d'`os.system`, d'`eval/exec/pickle` dans `src/` ; commandes en listes d'arguments ; la version donnée à `--revenir-a` doit avoir la forme `X.Y.Z` | OK |
| Actions « décharger / fermer » de la page Santé | Liste fermée d'actions ; ComfyUI n'est fermé que si Lutin l'a lancé | OK |
| Fichiers servis (`/fichier/`, `/lib/`, `/image/`, `/piece/`) | `..` et variantes encodées refusés | OK, `test_parcours_vierge.py` |
| Corps de requêtes | Plafonds (2 Mo de JSON, 8 Mo d'images, 20 Mo de documents) ; un `Content-Length` non numérique vaut « trop gros » ; le JSON doit être un objet | OK |
| Sites tiers et « rebinding » | `Host` / `Origin` vérifiés, jeton de page exigé en lecture au niveau 1 | OK (`test_serveur_securite.py`) |
| Fichiers de données | Un JSON abîmé ou du mauvais type retombe sur les valeurs par défaut (avant la 0.26.0, un `reglages.json` qui n'était pas un objet faisait planter chaque requête) | **Corrigé en 0.26.0** |
| Catalogue de moteurs signé | Ed25519, deux clés, altération et champs inconnus refusés | OK |

## Limites connues (non corrigées, dites franchement)

1. **Les mises à jour ne sont pas vérifiées au-delà de TLS.** `lutin update` installe la roue publiée sur GitHub ; il ne la compare pas au `SHA256SUMS.txt` publié à côté. Prévu : vérifier avant la 1.0 si cela peut être essayé sur une vraie publication.
2. **HTTP en clair sur le réseau local** (niveaux 2 et 3 sans certificat de proxy, et trafic entre machines) : qui peut lire le réseau lit ce qui y passe. Hors réseau de confiance, utilise le niveau 3 derrière un proxy TLS.
3. **Jeton de nœud et appairage** : une machine appairée peut faire tourner le moteur de celle qui le prête, dans la limite de deux demandes, jusqu'à ce que tu la révoques. Elle ne peut lire ni conversations, ni fichiers, ni réglages.
4. **Pas d'audit indépendant**, pas de campagne de fuzzing, pas de test d'intrusion.
5. **Docker** : non testé contre un utilisateur local hostile ; le conteneur ne monte pas le socket Docker.

## Signaler un problème

Voir [SECURITY.fr.md](SECURITY.fr.md).
