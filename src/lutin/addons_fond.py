"""Partie vivante de l'addon « fond » : le fil qui traite les documents en arrière-plan (voir fond.py)."""
from . import fond


def demarrer():
    fond.demarrer()


def arreter():
    fond.arreter()
