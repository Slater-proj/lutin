"""Aperçu d'une page : Lutin l'ouvre dans un navigateur sans fenêtre (Chrome, Edge ou Chromium déjà installé), la photographie et lit ce qu'elle affiche.

C'est ce qui permet de vérifier le rendu d'un fichier HTML ou d'un script avant de dire « c'est bon » : la capture est montrée à l'utilisateur dans la conversation, et le modèle reçoit le texte réellement affiché,
les erreurs de la console JavaScript et le titre de la page.

Garde-fous : seuls un fichier du dossier de travail ou une adresse de cette machine (127.0.0.1, localhost) sont ouverts ; profil temporaire jeté après (aucun cookie, aucune session) ; durée limitée ;
la page tourne dans le bac à sable du navigateur."""
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from . import moteur as _m
from .i18n import t as _t

DELAI = 40                # secondes au plus par lancement du navigateur
ATTENTE_MS = 3000         # temps virtuel laissé à la page pour se charger et s'animer
LARGEUR = (320, 3000)
HAUTEUR = (200, 4000)
TEXTE_MAX = 1800
RE_CONSOLE = re.compile(r'CONSOLE[^\]]*\]\s*"(.*?)"(?:, source: (\S+) \((\d+)\))?\s*$')


def navigateur():
    """La commande (liste) d'un navigateur Chromium installé, ou None. LUTIN_NAVIGATEUR impose un chemin."""
    impose = os.environ.get("LUTIN_NAVIGATEUR", "").strip()
    if impose and Path(impose).is_file():
        return [impose]
    candidats = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(var)
        if base:
            candidats += [Path(base) / "Google/Chrome/Application/chrome.exe", Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Chromium/Application/chrome.exe"]
    candidats += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    for c in candidats:
        if c.is_file():
            return [str(c)]
    for nom in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "microsoft-edge", "msedge"):
        trouve = shutil.which(nom)
        if trouve:
            return [trouve]
    return None


def adresse(cible):
    """L'adresse à ouvrir : un fichier du dossier de travail (chemin relatif) ou http://127.0.0.1|localhost[:port]/… ; sinon ErreurOutil."""
    cible = str(cible or "").strip()
    if re.match(r"^https?://", cible, re.I):
        hote = urllib.parse.urlsplit(cible).hostname
        if hote not in ("127.0.0.1", "localhost", "::1"):
            raise _m.ErreurOutil(_t("Seules les pages de cette machine (127.0.0.1, localhost) ou un fichier du dossier de travail peuvent être ouverts."))
        return cible
    from . import outils
    f = outils.chemin_sur(cible)
    if not f.is_file():
        raise _m.ErreurOutil(_t("Fichier introuvable : {}").format(cible))
    return f.as_uri()


def _lancer(commande, delai):
    return subprocess.run(commande, capture_output=True, timeout=delai, stdin=subprocess.DEVNULL)


def photographier(url, largeur=1200, hauteur=800, navigateur_=None):
    """(octets PNG, texte affiché, titre, messages de la console). Lève ErreurOutil si le navigateur manque ou ne produit rien."""
    nav = navigateur_ or navigateur()
    if not nav:
        raise _m.ErreurOutil(_t("Aucun navigateur (Chrome, Edge ou Chromium) n'est installé sur cette machine : l'aperçu est impossible."))
    largeur, hauteur = max(LARGEUR[0], min(LARGEUR[1], int(largeur))), max(HAUTEUR[0], min(HAUTEUR[1], int(hauteur)))
    with tempfile.TemporaryDirectory(prefix="lutin-apercu-") as tmp:
        sortie = Path(tmp) / "capture.png"
        base = nav + ["--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions", "--hide-scrollbars", "--mute-audio", "--user-data-dir=" + str(Path(tmp) / "profil"),
                      "--window-size=%d,%d" % (largeur, hauteur), "--virtual-time-budget=%d" % ATTENTE_MS]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            base.append("--no-sandbox")                                    # dans un conteneur (root), Chrome refuse sinon de démarrer
        try:
            photo = _lancer(base + ["--enable-logging=stderr", "--v=0", "--screenshot=" + str(sortie), url], DELAI)
            dom = _lancer(base + ["--dump-dom", url], DELAI)
        except subprocess.TimeoutExpired:
            raise _m.ErreurOutil(_t("La page n'a pas fini de se charger en {} secondes.").format(DELAI))
        except OSError as erreur:
            raise _m.ErreurOutil(_t("Le navigateur n'a pas pu démarrer : {}").format(erreur))
        if not sortie.is_file() or sortie.stat().st_size < 100:
            raise _m.ErreurOutil(_t("Le navigateur n'a produit aucune capture : {}").format(photo.stderr.decode("utf-8", "replace").strip()[-300:] or _t("(aucun message)")))
        png = sortie.read_bytes()
    console = []
    for ligne in photo.stderr.decode("utf-8", "replace").splitlines():
        m = RE_CONSOLE.search(ligne)
        if m:
            source = (" ({}:{})".format(os.path.basename(m.group(2)), m.group(3)) if m.group(2) else "")
            console.append(m.group(1)[:300] + source)
    html = dom.stdout.decode("utf-8", "replace")
    titre = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    sans = re.sub(r"<(head|script|style|noscript|template)\b.*?</\1>", " ", html, flags=re.S | re.I)
    texte = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", sans)).strip()
    import html as _html
    return png, _html.unescape(texte), _html.unescape(titre.group(1).strip()) if titre else "", console[:15]


def outil_apercu(cible, largeur, hauteur, ctx, navigateur_=None):
    """L'outil « apercu_page » : demande l'accord, photographie, montre la capture à l'utilisateur et décrit au modèle ce que la page affiche."""
    url = adresse(cible)
    largeur, hauteur = largeur or 1200, hauteur or 800
    try:
        largeur, hauteur = int(largeur), int(hauteur)
    except (TypeError, ValueError):
        raise _m.ErreurOutil(_t("Largeur et hauteur : des nombres entiers de pixels."))
    if not ctx["accord"](_t("Aperçu de la page"), _t("Ouvre {} dans un navigateur sans fenêtre (profil temporaire) et en prend une capture, {}×{}.").format(cible, largeur, hauteur), "", auto=ctx["auto_commandes"]):
        from . import outils
        return outils.refus(ctx, _t("Refusé par l'utilisateur : rien n'a été ouvert."))
    from . import images
    png, texte, titre, console = photographier(url, largeur, hauteur, navigateur_)
    ident = images.enregistrer(png)
    ctx.setdefault("medias", []).append(ident)
    erreurs = [c for c in console if re.search(r"Uncaught|Error|erreur|Failed|refused|404|not defined", c, re.I)]
    lignes = [_t("Capture faite ({}×{}) et montrée à l'utilisateur dans la conversation. Tu ne vois pas l'image : appuie-toi sur ce texte.").format(largeur, hauteur),
              _t("Titre de la page : {}").format(titre or _t("(aucun)")),
              _t("Texte affiché ({} caractères) : {}").format(len(texte), texte[:TEXTE_MAX] + (" …" if len(texte) > TEXTE_MAX else "") or _t("(la page est vide)"))]
    if console:
        lignes.append(_t("Console du navigateur ({} message(s), dont {} erreur(s)) :").format(len(console), len(erreurs)))
        lignes += ["- " + c for c in console]
    else:
        lignes.append(_t("Console du navigateur : aucun message."))
    return "\n".join(lignes)
