"""Lance chaque fichier de test dans SON PROPRE processus (le moteur garde des réglages globaux : deux fichiers dans un même processus se gêneraient).

    python tests/lancer_tests.py            tous les fichiers
    python tests/lancer_tests.py securite   seulement ceux dont le nom contient « securite »
Plusieurs fichiers à la fois (LUTIN_TESTS_PARALLELES=1 pour les lancer à la suite). Code de sortie 0 si tout passe. Utilisé tel quel par l'intégration continue.
"""
import concurrent.futures
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
DELAI_FICHIER_S = 900          # le plus long fichier (navigateur) prend environ 5 minutes sur une machine lente


def lancer(f):
    """Un fichier, et sur l'intégration continue (machine partagée, parfois lente) un second essai s'il échoue : un test qui ne passe qu'au second essai est signalé « instable » mais ne bloque pas ; deux échecs, si."""
    debut = time.time()
    f, r, _ = lancer_une_fois(f)
    if r.returncode != 0 and os.environ.get("GITHUB_ACTIONS"):
        premier = r
        f, r, _ = lancer_une_fois(f)
        if r.returncode == 0:
            r = subprocess.CompletedProcess(r.args, 0, (r.stdout or "") + "\ninstable : a échoué au premier essai, réussi au second. " + (premier.stderr or premier.stdout or "")[-400:], r.stderr)
            print("::warning title={} instable::a échoué une fois puis réussi".format(f.name), flush=True)
    return f, r, time.time() - debut


def lancer_une_fois(f):
    debut = time.time()
    try:
        r = subprocess.run([sys.executable, "-B", str(f)], cwd=tempfile.gettempdir(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=DELAI_FICHIER_S)
    except subprocess.TimeoutExpired as e:          # un test bloqué ne doit pas geler toute la suite : il compte comme un échec, avec ce qu'il avait écrit
        sortie = e.stdout or e.stderr or ""
        r = subprocess.CompletedProcess(e.cmd, 1, "", "Délai dépassé ({} s) : {}".format(DELAI_FICHIER_S, sortie if isinstance(sortie, str) else sortie.decode("utf-8", "replace")))
    return f, r, time.time() - debut


def ouvriers():
    """Combien de fichiers à la fois : LUTIN_TESTS_PARALLELES, sinon 3 (2 s'il y a peu de processeurs), 1 pour tout lancer à la suite. Chaque fichier a son processus, ses ports (choisis par le système) et ses dossiers temporaires : ils ne se gênent pas."""
    try:
        return max(1, int(os.environ.get("LUTIN_TESTS_PARALLELES", "")))
    except ValueError:
        return max(1, min(3, (os.cpu_count() or 2) - 1))


def principal(filtre=""):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Dossier de travail local : sous Windows, cmd.exe refuse de démarrer dans un chemin réseau (« \\serveur\partage ») et ajoute un message à la sortie des commandes.
    fichiers = sorted(f for f in ICI.glob("test_*.py") if filtre in f.name)
    # Les plus longs d'abord : le temps total approche celui du plus long fichier plutôt que celui de la somme.
    ordre = sorted(fichiers, key=lambda f: -f.stat().st_size)
    echecs = []
    with concurrent.futures.ThreadPoolExecutor(ouvriers()) as pool:
        for f, r, duree in pool.map(lancer, ordre):
            derniere = [ligne for ligne in (r.stderr or r.stdout).strip().splitlines() if ligne.strip()][-1:] or [""]
            print("{} {:<34} {:>5.1f} s  {}".format("✔" if r.returncode == 0 else "✘", f.name, duree, derniere[0]), flush=True)
            if r.returncode != 0:
                echecs.append(f.name)
                sortie = (r.stderr or r.stdout)[-6000:]
                print(sortie)
                if os.environ.get("GITHUB_ACTIONS"):                  # annotation visible sur la page de l'exécution (et par l'API) même sans accès aux journaux
                    message = sortie[-3500:].replace("%", "%25").replace(chr(13), "%0D").replace(chr(10), "%0A")
                    print("::error title={}::{}".format(f.name, message))
    print("\n{} fichier(s), {} en échec{}".format(len(fichiers), len(echecs), " : " + ", ".join(sorted(echecs)) if echecs else ""))
    return 1 if echecs or not fichiers else 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1] if len(sys.argv) > 1 else ""))
