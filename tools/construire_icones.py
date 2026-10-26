"""Fabrique les images du logo de Lutin, à la taille où il se voit. Le personnage est sans fond (transparent) partout où un fond ferait tache :
- src/lutin/web/logo.svg : onglet du navigateur et logo de la page (source faite à la main, rien à générer) ;
- src/lutin/web/lutin.ico : icône de la zone de notification (lutin zone) ;
- installateur/windows/lutin.ico : icône de lutin-setup-<version>.exe, des raccourcis et de la désinstallation (16, 32, 48, 256 px) ;
- installateur/windows/assistant-grand.bmp (164 × 314) et assistant-petit.bmp (55 × 58) : images de l'assistant d'installation (le personnage sur le fond de la page) ;
- src/lutin/web/icones/icone-180.png, icone-192.png, icone-512.png : icônes d'application (écran d'accueil du téléphone). Elles gardent leur tuile sombre : iOS remplit le transparent en noir.

Le transparent vient de Chrome, déjà installé : le SVG est rendu sur fond noir puis sur fond blanc ; la différence donne la transparence.
Usage (après un changement du logo ; les fichiers générés sont commités) :
    pip install pillow
    python tools/construire_icones.py
Pillow n'est nécessaire que pour cet outil, pas pour Lutin lui-même. Chrome est cherché à son emplacement habituel, ou dans la variable LUTIN_CHROME."""
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "src" / "lutin" / "web"
SVG = WEB / "logo.svg"
MASTER_TUILE = RACINE / "assets" / "logo-512.png"                 # le logo avec sa tuile sombre (icônes d'application seulement)
CADRAGE_TUILE = (56, 54, 476, 474)                                # carré de 420 px sur la source de 512 (mesuré : 80-452 × 58-470)
WINDOWS = RACINE / "installateur" / "windows"
FOND = (11, 15, 20)                                              # #0b0f14, le fond de la page
TAILLES_ICO = [(16, 16), (32, 32), (48, 48), (256, 256)]
CHROME = os.environ.get("LUTIN_CHROME") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TAILLE_RENDU = 1024


def chrome_rend(couleur_fond):
    """Le SVG affiché sur un fond uni, en image carrée de TAILLE_RENDU px."""
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text('<html><body style="margin:0;background:#{}"><img src="{}" style="width:{}px;height:{}px;display:block"></body></html>'.format(
            couleur_fond, SVG.resolve().as_uri(), TAILLE_RENDU, TAILLE_RENDU), encoding="utf-8")
        capture = Path(tmp) / "capture.png"
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--allow-file-access-from-files", "--window-size={},{}".format(TAILLE_RENDU, TAILLE_RENDU),
                        "--screenshot=" + str(capture), page.as_uri()], check=True, capture_output=True, timeout=120)
        return Image.open(capture).convert("RGB").crop((0, 0, TAILLE_RENDU, TAILLE_RENDU))


def logo_transparent():
    """Le personnage en RGBA, recadré sur lui-même et carré. Sur noir, une couleur vaut c·a : on garde cette couleur (les bords sont un peu sombres)."""
    noir, blanc = chrome_rend("000000"), chrome_rend("ffffff")
    alpha = ImageChops.subtract(blanc, noir).convert("L").point(lambda v: 255 - v)
    rgba = Image.merge("RGBA", (*noir.split(), alpha))         # bords légèrement assombris : négligeable à ces tailles
    boite = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    cote = max(boite[2] - boite[0], boite[3] - boite[1]) + 8
    cx, cy = (boite[0] + boite[2]) // 2, (boite[1] + boite[3]) // 2
    return rgba.crop((cx - cote // 2, cy - cote // 2, cx + cote // 2, cy + cote // 2))


def sur_fond(personnage, taille, marge):
    """Image pleine taille sur le fond de la page, le personnage centré (marge en px sur chaque bord)."""
    cote = min(taille) - 2 * marge
    image = Image.new("RGB", taille, FOND)
    image.paste(personnage.resize((cote, cote), Image.LANCZOS), ((taille[0] - cote) // 2, (taille[1] - cote) // 2), personnage.resize((cote, cote), Image.LANCZOS))
    return image


def main():
    personnage = logo_transparent()
    personnage.save(WEB / "lutin.ico", sizes=TAILLES_ICO)
    personnage.save(WINDOWS / "lutin.ico", sizes=TAILLES_ICO)
    sur_fond(personnage, (164, 314), 12).save(WINDOWS / "assistant-grand.bmp")
    sur_fond(personnage, (55, 58), 1).save(WINDOWS / "assistant-petit.bmp")
    tuile = Image.open(MASTER_TUILE).convert("RGBA").crop(CADRAGE_TUILE)
    for n in (180, 192, 512):
        tuile.resize((n, n), Image.LANCZOS).save(WEB / "icones" / "icone-{}.png".format(n))
    print("Images écrites dans", WEB, "et", WINDOWS)


if __name__ == "__main__":
    main()
