"""Fabrique les images de l'installateur Windows à partir du logo de Lutin (web/icones/icone-512.png) :
- installateur/windows/lutin.ico : icône de lutin-setup-<version>.exe, de l'entrée « Applications » et des raccourcis (16, 32, 48, 256 px) ;
- installateur/windows/assistant-grand.bmp (164 × 314) et assistant-petit.bmp (55 × 58) : images de l'assistant d'installation.

Usage (une fois, après avoir changé le logo ; les fichiers générés sont commités) :
    pip install pillow
    python tools/construire_icones_windows.py
Pillow n'est nécessaire que pour cet outil, pas pour Lutin lui-même."""
from pathlib import Path

from PIL import Image

RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "src" / "lutin" / "web" / "icones" / "icone-512.png"
SORTIE = RACINE / "installateur" / "windows"
FOND = (11, 15, 20)               # #0b0f14, le fond de la page
TAILLES_ICO = [(16, 16), (32, 32), (48, 48), (256, 256)]


def assistant(taille, logo_px, haut):
    """Image pleine taille sur le fond de la page, logo centré à la hauteur voulue."""
    image = Image.new("RGB", taille, FOND)
    logo = Image.open(SOURCE).convert("RGBA").resize((logo_px, logo_px), Image.LANCZOS)
    image.paste(logo, ((taille[0] - logo_px) // 2, haut), logo)
    return image


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    logo = Image.open(SOURCE).convert("RGBA")
    logo.save(SORTIE / "lutin.ico", sizes=TAILLES_ICO)
    assistant((164, 314), 120, 90).save(SORTIE / "assistant-grand.bmp")
    assistant((55, 58), 46, 6).save(SORTIE / "assistant-petit.bmp")
    print("Images écrites dans", SORTIE)


if __name__ == "__main__":
    main()
