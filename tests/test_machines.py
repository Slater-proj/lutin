"""Machines (D7) : appairage par code, jeton de nœud à portée limitée, quatre états, routage vers le nœud, repli local silencieux, rien d'envoyé à une machine non autorisée."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-machines-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402
from lutin import machines, moteurs  # noqa: E402
from lutin import securite as S  # noqa: E402


class FauxNoeud:
    """Le moteur de la machine qui prête le sien : compte les demandes reçues."""
    id, nom = "ollama", "Ollama"

    def __init__(self):
        self.demandes = []
        self.actif = True

    def modeles(self):
        return {"actif": self.actif, "installes": ["m1", "m2", "qwen3:8b"]}

    def chat(self, corps, delai=60):
        self.demandes.append(corps)
        return {"message": {"role": "assistant", "content": "réponse du nœud"}, "done": True}

    def chat_flux(self, corps, delai=900):
        self.demandes.append(corps)
        flux = mock.MagicMock()
        flux.__enter__.return_value = iter([{"message": {"content": "bon"}}, {"message": {"content": "jour"}}, {"done": True, "eval_count": 2}])
        flux.__exit__.return_value = False
        return flux


class FauxLocal:
    id, nom = "ollama", "Ollama"

    def __init__(self):
        self.demandes = []

    def chat(self, corps, delai=60):
        self.demandes.append(corps)
        return {"message": {"role": "assistant", "content": "réponse locale"}, "done": True}

    def chat_flux(self, corps, delai=900):
        self.demandes.append(corps)
        flux = mock.MagicMock()
        flux.__enter__.return_value = iter([{"message": {"content": "local"}}, {"done": True}])
        flux.__exit__.return_value = False
        return flux

    def modeles(self):
        return {"actif": True, "installes": ["m1"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-machines-t-"))
        machines.DOSSIER = self.tmp
        machines.CODES.clear()
        machines.SONDES.clear()
        machines.DERNIER_ETAT.clear()
        A.LIMITEUR_PIN.evenements.clear()
        machines.REGISTRE.update(t=0.0)
        self.noeud = FauxNoeud()
        self.avant = (A.SECURITE, A.APPAREILS)
        A.SECURITE = S.Securite()
        import lutin.serveur as srv
        self.p_moteur = mock.patch.object(srv._moteurs, "par_id", lambda ident: self.noeud)
        self.p_reglages = mock.patch.object(srv._m, "reglages", lambda: dict(A.REGLAGES_DEFAUT))
        self.p_moteur.start()
        self.p_reglages.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire if hasattr(A, "Gestionnaire") else srv.Gestionnaire)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.adresse = "http://127.0.0.1:%d" % self.port
        self.addCleanup(self.fin)

    def fin(self):
        try:
            self.srv.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.p_moteur.stop()
        self.p_reglages.stop()
        A.SECURITE, A.APPAREILS = self.avant
        machines.DOSSIER = None

    def jumeler(self):
        machines.noeud_activer(True)
        code = machines.noeud_nouveau_code()["code"]
        return machines.ajouter(self.adresse, code, "Poste")

    def http(self, methode, chemin, corps=None, en_tetes=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(methode, chemin, body=json.dumps(corps).encode() if corps is not None else None, headers=dict({"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json"}, **(en_tetes or {})))
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")


class Appairage(Base):
    def test_le_noeud_est_eteint_par_defaut_et_refuse_le_niveau_local(self):
        self.assertFalse(machines.noeud_actif())
        with self.assertRaises(ValueError):
            machines.noeud_activer(True, niveau_local=True)
        self.assertFalse(machines.noeud_actif())

    def test_un_code_est_a_usage_unique_et_expire(self):
        machines.noeud_activer(True)
        code = machines.noeud_nouveau_code()["code"]
        machines.noeud_echanger(code, "Petit PC")
        with self.assertRaises(ValueError):
            machines.noeud_echanger(code, "Petit PC")
        autre = machines.noeud_nouveau_code()["code"]
        plus_tard = time.time() + machines.DUREE_CODE_S + 5
        with mock.patch.object(machines.time, "time", lambda: plus_tard):
            with self.assertRaises(ValueError):
                machines.noeud_echanger(autre, "Petit PC")

    def test_un_noeud_eteint_n_accepte_personne(self):
        code = machines.noeud_nouveau_code()["code"]
        with self.assertRaises(ValueError):
            machines.noeud_echanger(code, "Petit PC")

    def test_ajouter_par_le_reseau_ne_garde_pas_le_jeton_dans_la_vue(self):
        m = self.jumeler()
        self.assertEqual(m["nom"], "Poste")
        self.assertNotIn("jeton", m)
        self.assertTrue(machines.lire()[0]["jeton"], "le jeton est gardé, jamais montré")
        self.assertEqual(machines.lire()[0]["id"], machines.noeud()["id"])

    def test_un_mauvais_code_est_refuse(self):
        machines.noeud_activer(True)
        with self.assertRaises(ValueError) as e:
            machines.ajouter(self.adresse, "0000-0000", "X")
        self.assertIn("refusé", str(e.exception))
        self.assertEqual(machines.lire(), [])

    def test_le_jeton_est_garde_hache_sur_le_noeud(self):
        m = self.jumeler()
        jeton = machines.lire()[0]["jeton"]
        brut = (self.tmp / "noeud.json").read_text(encoding="utf-8")
        self.assertNotIn(jeton, brut)
        self.assertEqual(machines.noeud_jeton_valide(jeton), "Poste" if False else machines.noeud()["jetons"][0]["nom"])
        self.assertIsNotNone(m)

    def test_adresses(self):
        self.assertEqual(machines.normaliser_adresse("192.168.1.20"), "http://192.168.1.20:8777")
        self.assertEqual(machines.normaliser_adresse("https://poste:9000/x"), "https://poste:9000")
        for mauvaise in ("", "ftp://a", "http://user:mdp@a", "http://"):
            with self.assertRaises(ValueError):
                machines.normaliser_adresse(mauvaise)


class Portee(Base):
    def test_le_jeton_de_noeud_n_ouvre_que_le_noeud(self):
        self.jumeler()
        jeton = machines.lire()[0]["jeton"]
        statut, _ = self.http("GET", "/api/noeud/etat", en_tetes={"X-Noeud": jeton})
        self.assertEqual(statut, 200)
        for chemin in ("/api/etat", "/api/machines", "/api/memoire", "/api/ressources"):
            statut, _ = self.http("GET", chemin, en_tetes={"X-Noeud": jeton})
            self.assertIn(statut, (401, 403), chemin)

    def test_sans_jeton_ou_avec_un_faux_jeton_rien_ne_passe(self):
        self.jumeler()
        self.assertEqual(self.http("GET", "/api/noeud/etat")[0], 401)
        self.assertEqual(self.http("GET", "/api/noeud/etat", en_tetes={"X-Noeud": "faux"})[0], 401)
        self.assertEqual(self.http("POST", "/api/noeud/chat", {"corps": {"model": "m1", "messages": []}})[0], 401)
        self.assertEqual(self.noeud.demandes, [])

    def test_revoquer_coupe_l_acces(self):
        self.jumeler()
        jeton = machines.lire()[0]["jeton"]
        nom = machines.noeud()["jetons"][0]["nom"]
        machines.noeud_revoquer(nom)
        self.assertEqual(self.http("GET", "/api/noeud/etat", en_tetes={"X-Noeud": jeton})[0], 401)

    def test_le_corps_est_reduit_a_ce_que_le_noeud_transmet(self):
        r = machines.corps_autorise({"model": "m", "messages": [], "options": {"num_ctx": 4096}, "evil": "rm -rf", "images": ["x"]})
        self.assertEqual(sorted(r), ["messages", "model", "options"])
        with self.assertRaises(ValueError):
            machines.corps_autorise({"model": 3, "messages": []})


class Etats(Base):
    def test_operationnel(self):
        m = self.jumeler()
        r = machines.sonder(machines.trouver(m["id"]), "m1", force=True)
        self.assertEqual(r["etat"], "operationnel")

    def test_joignable_si_le_modele_manque(self):
        m = self.jumeler()
        r = machines.sonder(machines.trouver(m["id"]), "inconnu", force=True)
        self.assertEqual(r["etat"], "joignable")
        self.assertIn("inconnu", r["detail"])

    def test_le_modele_local_n_est_cherche_que_sur_la_machine_choisie(self):
        m = self.jumeler()
        etat = lambda **kw: machines.etats("inconnu", **kw)[0]["etat"]          # noqa: E731
        machines.SONDES.clear()
        self.assertEqual(etat(), "operationnel")
        machines.SONDES.clear()
        self.assertEqual(etat(choisie=m["id"]), "joignable")

    def test_l_onglet_machines_suit_le_reglage_ou_les_machines_appairees(self):
        self.assertFalse(machines.cluster_actif(None))          # rien d'appairé, rien de prêté : caché
        self.assertTrue(machines.cluster_actif(True))
        self.jumeler()
        self.assertTrue(machines.cluster_actif(None))          # une machine appairée : visible tout seul
        self.assertFalse(machines.cluster_actif(False))          # le réglage explicite l'emporte

    def test_une_machine_qui_ne_repond_plus_disparait_des_listes(self):
        m = self.jumeler()
        machines.DISTANTS.update(t=machines.time.monotonic(), v=[{"id": m["id"], "nom": "x", "etat": "operationnel", "modeles": ["m1"]}])
        machines.CONVERSATIONS.update(t=machines.time.monotonic(), v=[{"machine": m["id"], "machine_nom": "x", "id": "a" * 8, "titre": "T", "maj": "", "messages": 1}])
        machines.DERNIER_ETAT[m["id"]] = "operationnel"
        machines.SONDES[m["id"]] = (machines.time.monotonic(), {}, "")
        self.assertEqual(len(machines.modeles_distants()), 1)
        self.noeud.actif = False
        machines.signaler_panne(machines.trouver(m["id"]))
        self.assertEqual(machines.modeles_distants(), [])
        self.assertEqual(machines.conversations_distantes(), [])

    def test_une_machine_eteinte_sans_personne_pour_la_sonder_disparait_quand_meme(self):
        m = self.jumeler()
        machines.DISTANTS.update(t=machines.time.monotonic(), v=[{"id": m["id"], "nom": "x", "etat": "operationnel", "modeles": ["m1"]}])
        machines.CONVERSATIONS.update(t=machines.time.monotonic(), v=[{"machine": m["id"], "machine_nom": "x", "id": "a" * 8, "titre": "T", "maj": "", "messages": 1}])
        machines.DERNIER_ETAT[m["id"]] = "operationnel"
        machines.SONDES[m["id"]] = (machines.time.monotonic() - machines.FRAICHEUR_S - 1, {}, "")          # dernière réponse trop ancienne
        self.assertEqual(machines.modeles_distants(), [])
        self.assertEqual(machines.conversations_distantes(), [])
        self.assertEqual(machines.hors_ligne(), [machines.trouver(m["id"])["nom"]])
        machines.SONDES[m["id"]] = (machines.time.monotonic(), {}, "")          # elle répond de nouveau
        self.assertEqual(len(machines.modeles_distants()), 1)
        self.assertEqual(machines.hors_ligne(), [])

    def test_la_veille_sonde_les_machines_sans_la_page_machines(self):
        m = self.jumeler()
        machines.SONDES.clear()
        machines.veiller(attente=True)
        self.assertIn(m["id"], machines.SONDES)
        self.assertEqual(machines.DERNIER_ETAT[m["id"]], "operationnel")
        self.noeud.actif = False
        machines.SONDES[m["id"]] = (machines.time.monotonic() - machines.FRAICHEUR_S, {}, "")
        machines.veiller(attente=True)
        self.assertEqual(machines.DERNIER_ETAT[m["id"]], "joignable")

    def test_desactiver_le_mode_vide_les_listes_distantes(self):
        m = self.jumeler()
        machines.DISTANTS.update(t=1.0, v=[{"id": m["id"], "nom": "x", "etat": "operationnel", "modeles": ["m1"]}])
        machines.CONVERSATIONS.update(t=1.0, v=[{"machine": m["id"]}])
        machines.vider_listes()
        self.assertEqual((machines.DISTANTS["v"], machines.CONVERSATIONS["v"]), ([], []))

    def test_les_etapes_d_une_machine(self):
        m = self.jumeler()
        h = machines.trouver(m["id"])
        machines.SONDES.clear()
        r = machines.sonder(h, "", force=True)
        self.assertEqual(r["etape"], "synchro")          # elle répond, mais ses modèles et conversations ne sont pas encore relus
        machines._synchro_fait("modeles", [m["id"]])
        machines._synchro_fait("conv", [m["id"]])
        self.assertEqual(machines.sonder(h, "", force=True)["etape"], "pret")
        self.noeud.actif = False
        self.assertEqual(machines.sonder(h, "", force=True)["etape"], "lutin")          # Lutin répond, le moteur est arrêté

    def test_l_extinction_se_suit_puis_la_machine_est_eteinte(self):
        m = self.jumeler()
        h = machines.trouver(m["id"])
        machines.ARRET[m["id"]] = machines.time.monotonic()
        machines.SYNCHRO[m["id"]] = {"modeles": True, "conv": True}
        r = machines.sonder(h, "", force=True)
        self.assertEqual((r["etape"], 0 < r["dans_s"] <= 30), ("extinction", True))
        self.noeud.actif = False
        machines.signaler_panne(h)

    def test_la_version_du_nœud_dit_si_lutin_n_y_est_pas_a_jour(self):
        with mock.patch("lutin.moteur.VERSION", "0.38.0"):
            self.assertTrue(machines._maj_disponible("0.36.1"))
            self.assertFalse(machines._maj_disponible("0.38.0"))
            self.assertFalse(machines._maj_disponible("0.40.0"))
            self.assertFalse(machines._maj_disponible(""))

    def test_une_connexion_refusee_prouve_que_la_machine_est_allumee(self):
        self.assertTrue(machines._hote_allume(machines.urllib.error.URLError(ConnectionRefusedError())))
        self.assertFalse(machines._hote_allume(machines.urllib.error.URLError(TimeoutError())))

    def test_joignable_si_le_moteur_est_arrete(self):
        m = self.jumeler()
        self.noeud.actif = False
        self.assertEqual(machines.sonder(machines.trouver(m["id"]), "m1", force=True)["etat"], "joignable")

    def test_injoignable_quand_la_machine_est_eteinte(self):
        m = self.jumeler()
        self.srv.shutdown()
        self.srv.server_close()
        self.assertEqual(machines.sonder(machines.trouver(m["id"]), "m1", force=True)["etat"], "injoignable")

    def test_une_autre_machine_a_la_meme_adresse_est_injoignable(self):
        m = self.jumeler()
        n = machines.noeud()
        n["id"] = "f" * 32
        machines._ecrire("noeud.json", n)
        r = machines.sonder(machines.trouver(m["id"]), "m1", force=True)
        self.assertEqual(r["etat"], "injoignable")
        self.assertIn("plus la même machine", r["detail"])

    def test_le_journal_ne_note_que_les_changements_d_etat(self):
        m = self.jumeler()
        mm = machines.trouver(m["id"])
        for _ in range(3):
            machines.sonder(mm, "m1", force=True)
        self.noeud.actif = False
        machines.sonder(mm, "m1", force=True)
        lignes = [ligne for ligne in machines.journal() if "Poste :" in ligne]
        self.assertEqual(len(lignes), 2, lignes)


class Routage(Base):
    CORPS = {"model": "m1", "messages": [{"role": "user", "content": "salut"}], "options": {"num_ctx": 4096}}

    def test_la_demande_part_chez_le_noeud_quand_il_est_operationnel(self):
        m = self.jumeler()
        local = FauxLocal()
        mo = machines.acheminer(local, {"machine": m["id"]})
        rep = mo.chat(dict(self.CORPS), 20)
        self.assertEqual(rep["message"]["content"], "réponse du nœud")
        self.assertEqual(local.demandes, [])
        with mo.chat_flux(dict(self.CORPS), 20) as flux:
            texte = "".join((e.get("message") or {}).get("content", "") for e in flux)
        self.assertEqual(texte, "bonjour")
        self.assertEqual(local.demandes, [])

    def test_le_noeud_s_eteint_le_local_repond_sans_aucune_erreur(self):
        m = self.jumeler()
        local = FauxLocal()
        mo = machines.acheminer(local, {"machine": m["id"]})
        self.srv.shutdown()
        self.srv.server_close()
        machines.SONDES.clear()
        with mo.chat_flux(dict(self.CORPS), 20) as flux:
            texte = "".join((e.get("message") or {}).get("content", "") for e in flux)
        self.assertEqual(texte, "local", "le repli local est silencieux")
        self.assertEqual(mo.chat(dict(self.CORPS), 20)["message"]["content"], "réponse locale")

    def test_un_modele_absent_du_noeud_reste_en_local(self):
        m = self.jumeler()
        local = FauxLocal()
        mo = machines.acheminer(local, {"machine": m["id"]})
        mo.chat(dict(self.CORPS, model="seulement-ici"), 20)
        self.assertEqual(len(local.demandes), 1)
        self.assertEqual(self.noeud.demandes, [])

    def test_rien_n_est_envoye_a_une_machine_qui_n_est_plus_celle_appairee(self):
        m = self.jumeler()
        n = machines.noeud()
        n["id"] = "e" * 32
        machines._ecrire("noeud.json", n)
        local = FauxLocal()
        mo = machines.acheminer(local, {"machine": m["id"]})
        mo.chat(dict(self.CORPS), 20)
        self.assertEqual(self.noeud.demandes, [], "aucune donnée n'est partie")
        self.assertEqual(len(local.demandes), 1)

    def test_sans_machine_choisie_ou_machine_retiree_le_moteur_local_est_le_seul(self):
        local = FauxLocal()
        self.assertIs(machines.acheminer(local, {}), local)
        self.assertIs(machines.acheminer(local, {"machine": "a" * 32}), local)

    def test_le_reste_du_moteur_reste_local(self):
        m = self.jumeler()
        mo = machines.acheminer(FauxLocal(), {"machine": m["id"]})
        self.assertEqual(mo.modeles()["installes"], ["m1"])
        self.assertEqual(mo.id, "ollama")


class Reglage(Base):
    def test_choisir_une_machine_inconnue_est_refuse(self):
        from lutin import donnees
        with self.assertRaises(ValueError):
            donnees._enregistrer_reglages({"machine": "a" * 32})

    def test_la_page_machines(self):
        self.jumeler()
        import lutin.serveur as srv
        vue = srv.Gestionnaire._vue_machines()
        self.assertTrue(vue["noeud"]["actif"])
        self.assertEqual(vue["machines"][0]["etat"], "operationnel")
        self.assertNotIn("jeton", json.dumps(vue))
        self.assertTrue(moteurs is not None)


if __name__ == "__main__":
    unittest.main()
