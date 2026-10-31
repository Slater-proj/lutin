"""Partie vivante de l'addon « mission » : le fil qui mène les missions longues (voir mission.py)."""
from . import mission


def demarrer():
    mission.demarrer()


def arreter():
    mission.arreter()


def etat():
    return mission.etat()


def action(nom, donnees):
    try:
        return mission.action(nom, donnees)
    except ValueError as e:
        from .addons import ErreurAddon
        raise ErreurAddon(str(e))
