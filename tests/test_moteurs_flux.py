"""Le flux interruptible : Arrêter coupe l'ouverture comme la lecture, les erreurs du moteur arrivent chez l'appelant."""
import threading
import time
import unittest

import context  # noqa: F401
from lutin import engines


class Flux:
    def __init__(self, evenements=(), bloque=False, erreur=None):
        self.evenements, self.bloque, self.erreur = list(evenements), bloque, erreur
        self.coupe = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        for e in self.evenements:
            yield e
        if self.erreur:
            raise self.erreur
        if self.bloque:
            self.coupe.wait(30)


class FluxInterruptible(unittest.TestCase):
    def test_les_evenements_passent_dans_l_ordre(self):
        with engines.FluxInterruptible(lambda: Flux([{"a": 1}, {"a": 2}]), threading.Event()) as flux:
            self.assertEqual(list(flux), [{"a": 1}, {"a": 2}])

    def test_arreter_coupe_un_flux_qui_ne_donne_plus_rien(self):
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        debut = time.time()
        with engines.FluxInterruptible(lambda: Flux([{"a": 1}], bloque=True), stop) as flux:
            vus = list(flux)
        self.assertEqual(vus, [{"a": 1}, {"__stop__": True}])
        self.assertLess(time.time() - debut, 3)

    def test_arreter_coupe_aussi_l_ouverture_de_la_connexion(self):
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()

        def ouvrir():
            time.sleep(10)          # un modèle qui charge : la réponse n'arrive pas
            return Flux()
        debut = time.time()
        with engines.FluxInterruptible(ouvrir, stop) as flux:
            vus = list(flux)
        self.assertEqual(vus, [{"__stop__": True}])
        self.assertLess(time.time() - debut, 3)

    def test_une_erreur_du_moteur_est_relevee_chez_l_appelant(self):
        with self.assertRaises(OSError):
            with engines.FluxInterruptible(lambda: Flux([{"a": 1}], erreur=OSError("coupé")), threading.Event()) as flux:
                list(flux)
        with self.assertRaises(ValueError):
            def ouvrir():
                raise ValueError("refusé")
            with engines.FluxInterruptible(ouvrir, threading.Event()) as flux:
                list(flux)


if __name__ == "__main__":
    unittest.main()
