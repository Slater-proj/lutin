"""Lance chaque fichier de test dans SON PROPRE processus (le moteur garde des réglages globaux : deux fichiers dans un même processus se gêneraient).

    python tests/lancer_tests.py            tous les fichiers
    python tests/lancer_tests.py securite   seulement ceux dont le nom contient « securite »
Code de sortie 0 si tout passe. Utilisé tel quel par l'intégration continue.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent


def principal(filtre=""):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Dossier de travail local : sous Windows, cmd.exe refuse de démarrer dans un chemin réseau (\\serveur\partage) et ajoute un message à la sortie des commandes.
    fichiers = sorted(f for f in ICI.glob("test_*.py") if filtre in f.name)
    echecs = []
    for f in fichiers:
        debut = time.time()
        r = subprocess.run([sys.executable, "-B", str(f)], cwd=tempfile.gettempdir(), capture_output=True, text=True, encoding="utf-8", errors="replace")
        derniere = [ligne for ligne in (r.stderr or r.stdout).strip().splitlines() if ligne.strip()][-1:] or [""]
        print("{} {:<34} {:>5.1f} s  {}".format("✔" if r.returncode == 0 else "✘", f.name, time.time() - debut, derniere[0]))
        if r.returncode != 0:
            echecs.append(f.name)
            sortie = (r.stderr or r.stdout)[-6000:]
            print(sortie)
            if os.environ.get("GITHUB_ACTIONS"):                  # annotation visible sur la page de l'exécution (et par l'API) même sans accès aux journaux
                message = sortie[-3500:].replace("%", "%25").replace(chr(13), "%0D").replace(chr(10), "%0A")
                print("::error title={}::{}".format(f.name, message))
    print("\n{} fichier(s), {} en échec{}".format(len(fichiers), len(echecs), " : " + ", ".join(echecs) if echecs else ""))
    return 1 if echecs or not fichiers else 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1] if len(sys.argv) > 1 else ""))
