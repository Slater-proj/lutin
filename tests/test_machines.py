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

from lutin import core as A  # noqa: E402
from lutin import machines, engines  # noqa: E402
from lutin import security as S  # noqa: E402
import quiet_node  # noqa: E402  (what a node reads of this computer, replaced)


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
        quiet_node.quiet(self)
        machines.FOLDER = self.tmp
        machines.CODES.clear()
        machines.PROBES.clear()
        machines.LAST_STATE.clear()
        A.PIN_LIMITER.evenements.clear()
        machines.REGISTRY.update(t=0.0)
        self.noeud = FauxNoeud()
        self.avant = (A.SECURITY, A.DEVICES)
        A.SECURITY = S.Security()
        import lutin.server as srv
        self.p_moteur = mock.patch.object(srv._moteurs, "by_id", lambda ident: self.noeud)
        self.p_reglages = mock.patch.object(srv._m, "settings", lambda: dict(A.DEFAULT_SETTINGS))
        self.p_moteur.start()
        self.p_reglages.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler if hasattr(A, "Handler") else srv.Handler)
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
        A.SECURITY, A.DEVICES = self.avant
        machines.FOLDER = None

    def jumeler(self):
        machines.node_enable(True)
        code = machines.node_new_code()["code"]
        return machines.add(self.adresse, code, "Poste")

    def http(self, methode, chemin, corps=None, en_tetes=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(methode, chemin, body=json.dumps(corps).encode() if corps is not None else None, headers=dict({"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json"}, **(en_tetes or {})))
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")


class Appairage(Base):
    def test_le_noeud_est_eteint_par_defaut_et_refuse_le_niveau_local(self):
        self.assertFalse(machines.node_active())
        with self.assertRaises(ValueError):
            machines.node_enable(True, niveau_local=True)
        self.assertFalse(machines.node_active())

    def test_un_code_est_a_usage_unique_et_expire(self):
        machines.node_enable(True)
        code = machines.node_new_code()["code"]
        machines.node_exchange(code, "Petit PC")
        with self.assertRaises(ValueError):
            machines.node_exchange(code, "Petit PC")
        autre = machines.node_new_code()["code"]
        plus_tard = time.time() + machines.CODE_TTL_S + 5
        with mock.patch.object(machines.time, "time", lambda: plus_tard):
            with self.assertRaises(ValueError):
                machines.node_exchange(autre, "Petit PC")

    def test_un_noeud_eteint_n_accepte_personne(self):
        code = machines.node_new_code()["code"]
        with self.assertRaises(ValueError):
            machines.node_exchange(code, "Petit PC")

    def test_ajouter_par_le_reseau_ne_garde_pas_le_jeton_dans_la_vue(self):
        m = self.jumeler()
        self.assertEqual(m["nom"], "Poste")
        self.assertNotIn("jeton", m)
        self.assertTrue(machines.read()[0]["jeton"], "le jeton est gardé, jamais montré")
        self.assertEqual(machines.read()[0]["id"], machines.node()["id"])

    def test_un_mauvais_code_est_refuse(self):
        machines.node_enable(True)
        with self.assertRaises(ValueError) as e:
            machines.add(self.adresse, "0000-0000", "X")
        self.assertIn("refusé", str(e.exception))
        self.assertEqual(machines.read(), [])

    def test_le_jeton_est_garde_hache_sur_le_noeud(self):
        m = self.jumeler()
        jeton = machines.read()[0]["jeton"]
        brut = (self.tmp / "noeud.json").read_text(encoding="utf-8")
        self.assertNotIn(jeton, brut)
        self.assertEqual(machines.node_token_valid(jeton), "Poste" if False else machines.node()["jetons"][0]["nom"])
        self.assertIsNotNone(m)

    def test_adresses(self):
        self.assertEqual(machines.normalize_address("192.168.1.20"), "http://192.168.1.20:8777")
        self.assertEqual(machines.normalize_address("https://poste:9000/x"), "https://poste:9000")
        for mauvaise in ("", "ftp://a", "http://user:mdp@a", "http://"):
            with self.assertRaises(ValueError):
                machines.normalize_address(mauvaise)


class Portee(Base):
    def test_le_jeton_de_noeud_n_ouvre_que_le_noeud(self):
        self.jumeler()
        jeton = machines.read()[0]["jeton"]
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
        jeton = machines.read()[0]["jeton"]
        nom = machines.node()["jetons"][0]["nom"]
        machines.node_revoke(nom)
        self.assertEqual(self.http("GET", "/api/noeud/etat", en_tetes={"X-Noeud": jeton})[0], 401)

    def test_le_corps_est_reduit_a_ce_que_le_noeud_transmet(self):
        r = machines.allowed_body({"model": "m", "messages": [], "options": {"num_ctx": 4096}, "evil": "rm -rf", "images": ["x"]})
        self.assertEqual(sorted(r), ["messages", "model", "options"])
        with self.assertRaises(ValueError):
            machines.allowed_body({"model": 3, "messages": []})


class Etats(Base):
    def test_operationnel(self):
        m = self.jumeler()
        r = machines.probe(machines.find(m["id"]), "m1", force=True)
        self.assertEqual(r["etat"], "operationnel")

    def test_joignable_si_le_modele_manque(self):
        m = self.jumeler()
        r = machines.probe(machines.find(m["id"]), "inconnu", force=True)
        self.assertEqual(r["etat"], "joignable")
        self.assertIn("inconnu", r["detail"])

    def test_le_modele_local_n_est_cherche_que_sur_la_machine_choisie(self):
        m = self.jumeler()
        etat = lambda **kw: machines.states("inconnu", **kw)[0]["etat"]          # noqa: E731
        machines.PROBES.clear()
        self.assertEqual(etat(), "operationnel")
        machines.PROBES.clear()
        self.assertEqual(etat(choisie=m["id"]), "joignable")

    def test_l_onglet_machines_suit_le_reglage_ou_les_machines_appairees(self):
        self.assertFalse(machines.cluster_active(None))          # rien d'appairé, rien de prêté : caché
        self.assertTrue(machines.cluster_active(True))
        self.jumeler()
        self.assertTrue(machines.cluster_active(None))          # une machine appairée : visible tout seul
        self.assertFalse(machines.cluster_active(False))          # le réglage explicite l'emporte

    def test_une_machine_qui_ne_repond_plus_disparait_des_listes(self):
        m = self.jumeler()
        machines.REMOTES.update(t=machines.time.monotonic(), v=[{"id": m["id"], "nom": "x", "etat": "operationnel", "modeles": ["m1"]}])
        machines.CONVERSATIONS.update(t=machines.time.monotonic(), v=[{"machine": m["id"], "machine_nom": "x", "id": "a" * 8, "titre": "T", "maj": "", "messages": 1}])
        machines.LAST_STATE[m["id"]] = "operationnel"
        machines.PROBES[m["id"]] = (machines.time.monotonic(), {}, "")
        self.assertEqual(len(machines.remote_models()), 1)
        self.noeud.actif = False
        machines.report_failure(machines.find(m["id"]))
        self.assertEqual(machines.remote_models(), [])
        self.assertEqual(machines.remote_conversations(), [])

    def test_une_machine_eteinte_sans_personne_pour_la_sonder_disparait_quand_meme(self):
        m = self.jumeler()
        machines.REMOTES.update(t=machines.time.monotonic(), v=[{"id": m["id"], "nom": "x", "etat": "operationnel", "modeles": ["m1"]}])
        machines.CONVERSATIONS.update(t=machines.time.monotonic(), v=[{"machine": m["id"], "machine_nom": "x", "id": "a" * 8, "titre": "T", "maj": "", "messages": 1}])
        machines.LAST_STATE[m["id"]] = "operationnel"
        machines.PROBES[m["id"]] = (machines.time.monotonic() - machines.FRESHNESS_S - 1, {}, "")          # dernière réponse trop ancienne
        with mock.patch.object(machines, "watch", lambda attente=False: None):          # « sans personne pour la sonder » : aucune sonde ne part en arrière-plan pendant le constat
            self.assertEqual(machines.remote_models(), [])
            self.assertEqual(machines.remote_conversations(), [])
            self.assertEqual(machines.offline_names(), [machines.find(m["id"])["nom"]])
        machines.PROBES[m["id"]] = (machines.time.monotonic(), {}, "")          # elle répond de nouveau
        self.assertEqual(len(machines.remote_models()), 1)
        self.assertEqual(machines.offline_names(), [])

    def test_la_veille_sonde_les_machines_sans_la_page_machines(self):
        m = self.jumeler()
        machines.PROBES.clear()
        machines.watch(attente=True)
        self.assertIn(m["id"], machines.PROBES)
        self.assertEqual(machines.LAST_STATE[m["id"]], "operationnel")
        self.noeud.actif = False
        machines.PROBES[m["id"]] = (machines.time.monotonic() - machines.FRESHNESS_S, {}, "")
        machines.watch(attente=True)
        self.assertEqual(machines.LAST_STATE[m["id"]], "joignable")

    def test_desactiver_le_mode_vide_les_listes_distantes(self):
        m = self.jumeler()
        machines.REMOTES.update(t=1.0, v=[{"id": m["id"], "nom": "x", "etat": "operationnel", "modeles": ["m1"]}])
        machines.CONVERSATIONS.update(t=1.0, v=[{"machine": m["id"]}])
        machines.clear_lists()
        self.assertEqual((machines.REMOTES["v"], machines.CONVERSATIONS["v"]), ([], []))

    def test_les_etapes_d_une_machine(self):
        m = self.jumeler()
        h = machines.find(m["id"])
        machines.PROBES.clear()
        r = machines.probe(h, "", force=True)
        self.assertEqual(r["etape"], "synchro")          # elle répond, mais ses modèles et conversations ne sont pas encore relus
        machines._sync_done("modeles", [m["id"]])
        machines._sync_done("conv", [m["id"]])
        self.assertEqual(machines.probe(h, "", force=True)["etape"], "pret")
        self.noeud.actif = False
        self.assertEqual(machines.probe(h, "", force=True)["etape"], "lutin")          # Lutin répond, le moteur est arrêté

    def test_l_extinction_se_suit_puis_la_machine_est_eteinte(self):
        m = self.jumeler()
        h = machines.find(m["id"])
        machines.SHUTDOWN[m["id"]] = machines.time.monotonic()
        machines.SYNC[m["id"]] = {"modeles": True, "conv": True}
        r = machines.probe(h, "", force=True)
        self.assertEqual((r["etape"], 0 < r["dans_s"] <= 30), ("extinction", True))
        self.noeud.actif = False
        machines.report_failure(h)

    def test_la_version_du_nœud_dit_si_lutin_n_y_est_pas_a_jour(self):
        with mock.patch("lutin.core.VERSION", "0.38.0"):
            self.assertTrue(machines._update_available("0.36.1"))
            self.assertFalse(machines._update_available("0.38.0"))
            self.assertFalse(machines._update_available("0.40.0"))
            self.assertFalse(machines._update_available(""))

    def test_une_connexion_refusee_prouve_que_la_machine_est_allumee(self):
        self.assertTrue(machines._host_on(machines.urllib.error.URLError(ConnectionRefusedError())))
        self.assertFalse(machines._host_on(machines.urllib.error.URLError(TimeoutError())))

    def test_joignable_si_le_moteur_est_arrete(self):
        m = self.jumeler()
        self.noeud.actif = False
        self.assertEqual(machines.probe(machines.find(m["id"]), "m1", force=True)["etat"], "joignable")

    def test_injoignable_quand_la_machine_est_eteinte(self):
        m = self.jumeler()
        self.srv.shutdown()
        self.srv.server_close()
        self.assertEqual(machines.probe(machines.find(m["id"]), "m1", force=True)["etat"], "injoignable")

    def test_une_autre_machine_a_la_meme_adresse_est_injoignable(self):
        m = self.jumeler()
        n = machines.node()
        n["id"] = "f" * 32
        machines._write("noeud.json", n)
        r = machines.probe(machines.find(m["id"]), "m1", force=True)
        self.assertEqual(r["etat"], "injoignable")
        self.assertIn("plus la même machine", r["detail"])

    def test_le_journal_ne_note_que_les_changements_d_etat(self):
        m = self.jumeler()
        mm = machines.find(m["id"])
        for _ in range(3):
            machines.probe(mm, "m1", force=True)
        self.noeud.actif = False
        machines.probe(mm, "m1", force=True)
        lignes = [ligne for ligne in machines.read_log() if "Poste :" in ligne]
        self.assertEqual(len(lignes), 2, lignes)


class Routage(Base):
    CORPS = {"model": "m1", "messages": [{"role": "user", "content": "salut"}], "options": {"num_ctx": 4096}}

    def test_la_demande_part_chez_le_noeud_quand_il_est_operationnel(self):
        m = self.jumeler()
        local = FauxLocal()
        mo = machines.route(local, {"machine": m["id"]})
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
        mo = machines.route(local, {"machine": m["id"]})
        self.srv.shutdown()
        self.srv.server_close()
        machines.PROBES.clear()
        with mo.chat_flux(dict(self.CORPS), 20) as flux:
            texte = "".join((e.get("message") or {}).get("content", "") for e in flux)
        self.assertEqual(texte, "local", "le repli local est silencieux")
        self.assertEqual(mo.chat(dict(self.CORPS), 20)["message"]["content"], "réponse locale")

    def test_un_modele_absent_du_noeud_reste_en_local(self):
        m = self.jumeler()
        local = FauxLocal()
        mo = machines.route(local, {"machine": m["id"]})
        mo.chat(dict(self.CORPS, model="seulement-ici"), 20)
        self.assertEqual(len(local.demandes), 1)
        self.assertEqual(self.noeud.demandes, [])

    def test_rien_n_est_envoye_a_une_machine_qui_n_est_plus_celle_appairee(self):
        m = self.jumeler()
        n = machines.node()
        n["id"] = "e" * 32
        machines._write("noeud.json", n)
        local = FauxLocal()
        mo = machines.route(local, {"machine": m["id"]})
        mo.chat(dict(self.CORPS), 20)
        self.assertEqual(self.noeud.demandes, [], "aucune donnée n'est partie")
        self.assertEqual(len(local.demandes), 1)

    def test_sans_machine_choisie_ou_machine_retiree_le_moteur_local_est_le_seul(self):
        local = FauxLocal()
        self.assertIs(machines.route(local, {}), local)
        self.assertIs(machines.route(local, {"machine": "a" * 32}), local)

    def test_le_reste_du_moteur_reste_local(self):
        m = self.jumeler()
        mo = machines.route(FauxLocal(), {"machine": m["id"]})
        self.assertEqual(mo.modeles()["installes"], ["m1"])
        self.assertEqual(mo.id, "ollama")


class Reglage(Base):
    def test_un_fichier_tenu_un_instant_n_est_ni_lu_vide_ni_impossible_a_remplacer(self):
        """Sous Windows, un fichier tenu un instant (une lecture hors du verrou pendant le remplacement, un antivirus) ne se lit pas ou ne se remplace
        pas. _lire rendait alors le défaut ({}) à une modification qui réécrivait le fichier sans le reste ; _ecrire échouait (nom temporaire commun,
        pas de nouvel essai). Les deux attendent un instant."""
        machines._write("noeud.json", {"partage": True, "nom": "atelier"})
        vrai_lire, vrai_remplacer, refus = Path.read_text, os.replace, []

        def tenu(chemin, *a, **k):
            if chemin.name == "noeud.json" and len(refus) < 2:
                refus.append(chemin)
                raise PermissionError(13, "Access is denied", str(chemin))
            return vrai_lire(chemin, *a, **k)
        with mock.patch.object(Path, "read_text", tenu):
            self.assertEqual(machines._read("noeud.json", {}), {"partage": True, "nom": "atelier"})
        essais = []

        def remplacer(source, cible):
            essais.append(cible)
            if len(essais) < 3:
                raise PermissionError(13, "Access is denied", str(cible))
            return vrai_remplacer(source, cible)
        with mock.patch.object(os, "replace", remplacer):
            machines._write("noeud.json", {"partage": False, "nom": "atelier"})
        self.assertEqual(machines._read("noeud.json", {}), {"partage": False, "nom": "atelier"})

    def test_choisir_une_machine_inconnue_est_refuse(self):
        from lutin import storage
        with self.assertRaises(ValueError):
            storage._save_settings({"machine": "a" * 32})

    def test_la_page_machines(self):
        self.jumeler()
        import lutin.server as srv
        vue = srv.Handler._vue_machines()
        self.assertTrue(vue["noeud"]["actif"])
        self.assertEqual(vue["machines"][0]["etat"], "operationnel")
        self.assertNotIn("jeton", json.dumps(vue))
        self.assertTrue(engines is not None)


class Demandes(Base):
    """Une machine appairée DEMANDE un droit ; rien n'est accordé tant que le propriétaire de l'hôte n'a pas répondu."""

    def preparer(self):
        m = self.jumeler()
        self.jeton = machines.find(m["id"])["jeton"]
        self.nom = machines.node()["jetons"][0]["nom"]
        return m

    def demander(self, droit, jeton=None):
        return self.http("POST", "/api/noeud/demande", {"droit": droit}, {"X-Noeud": self.jeton if jeton is None else jeton})

    def test_une_demande_n_accorde_rien_et_attend_la_reponse(self):
        self.preparer()
        self.assertEqual(self.demander("piloter")[0], 200)
        v = machines.node_view()
        self.assertFalse(v["piloter"])
        self.assertEqual([d["droit"] for d in v["demandes"]], ["piloter"])

    def test_sans_jeton_ou_pour_un_droit_inconnu_c_est_refuse(self):
        self.preparer()
        self.assertEqual(self.demander("piloter", jeton="")[0], 401)
        self.assertEqual(self.demander("piloter", jeton="x" * 40)[0], 401)
        for droit in ("skills", "tout", ""):
            self.assertEqual(self.demander(droit)[0], 400, droit)
        self.assertEqual(machines.node_view()["demandes"], [])

    def test_redemander_ne_fait_pas_de_doublon(self):
        self.preparer()
        for _ in range(3):
            self.demander("maj")
        self.assertEqual(len(machines.node_view()["demandes"]), 1)

    def test_accepter_active_le_droit_refuser_n_active_rien(self):
        self.preparer()
        self.demander("maj")
        self.demander("extinction")
        machines.node_answer_request(self.nom, "maj", True)
        machines.node_answer_request(self.nom, "extinction", False)
        v = machines.node_view()
        self.assertTrue(v["maj"])
        self.assertFalse(v["extinction"])
        self.assertEqual(v["demandes"], [])
        with self.assertRaises(ValueError):
            machines.node_answer_request(self.nom, "maj", True)

    def test_un_droit_deja_accorde_ne_laisse_pas_de_demande(self):
        self.preparer()
        machines.node_allow_control(True)
        self.demander("piloter")
        self.assertEqual(machines.node_view()["demandes"], [])

    def test_l_etat_ne_montre_que_les_demandes_de_celui_qui_interroge(self):
        m = self.preparer()
        self.demander("piloter")
        _, corps = self.http("GET", "/api/noeud/etat", None, {"X-Noeud": self.jeton})
        self.assertEqual(json.loads(corps)["demandes"], ["piloter"])
        with machines.LOCK:
            n = machines.node()
            n["demandes"].append({"machine": "Autre", "droit": "extinction", "date": "x"})
            machines._write("noeud.json", n)
        _, corps = self.http("GET", "/api/noeud/etat", None, {"X-Noeud": self.jeton})
        self.assertEqual(json.loads(corps)["demandes"], ["piloter"])
        self.assertEqual(machines.probe(machines.find(m["id"]), "", force=True)["demandes"], ["piloter"])

    def test_la_machine_principale_envoie_la_demande(self):
        m = self.preparer()
        self.assertEqual(machines.request_right(m["id"], "maj"), {"ok": True})
        self.assertEqual([d["droit"] for d in machines.node_view()["demandes"]], ["maj"])
        with self.assertRaises(ValueError):
            machines.request_right(m["id"], "skills")
        with self.assertRaises(ValueError):
            machines.request_right("0" * 32, "maj")

    def test_une_sonde_d_une_machine_qui_s_allume_est_refaite_vite(self):
        m = self.preparer()
        machines.PROBES[m["id"]] = (time.monotonic() - 3, {"etat": "injoignable"}, "")
        with mock.patch.object(machines, "_json", side_effect=OSError("x")) as j:
            machines.probe(machines.find(m["id"]), "")
        self.assertTrue(j.called, "un état « pas encore opérationnel » vieux de 3 s est resondé")


class Relais(Base):
    """Une conversation menée SUR l'hôte : le tour s'exécute là-bas, la machine appairée ne fait que passer les octets. Droit « piloter », décoché par défaut."""

    def preparer(self, piloter=True):
        m = self.jumeler()
        machines.node_allow_control(piloter)
        self.jeton = machines.find(m["id"])["jeton"]
        conv = A.conv_new()
        conv["messages"] = [{"role": "user", "content": "bonjour"}, {"role": "assistant", "content": "salut"}]
        conv["titre"] = "Sur l'hôte"
        A.conv_write(conv)
        return m, conv

    def relais(self, methode, chemin, corps=None, jeton=None):
        return self.http(methode, "/api/noeud/relais" + chemin, corps, {"X-Noeud": self.jeton if jeton is None else jeton})

    def test_sans_le_droit_rien_ne_passe(self):
        m, conv = self.preparer(piloter=False)
        statut, _ = self.relais("GET", "/api/conversation?id=" + conv["id"])
        self.assertEqual(statut, 403)
        self.assertFalse(machines.node_view()["piloter"])

    def test_sans_jeton_ou_avec_un_mauvais_jeton_c_est_refuse(self):
        m, conv = self.preparer()
        self.assertEqual(self.relais("GET", "/api/conversation?id=" + conv["id"], jeton="")[0], 401)
        self.assertEqual(self.relais("GET", "/api/conversation?id=" + conv["id"], jeton="x" * 40)[0], 401)

    def test_la_conversation_se_lit_sans_cookie_ni_jeton_de_page(self):
        m, conv = self.preparer()
        statut, corps = self.relais("GET", "/api/conversation?id=" + conv["id"])
        self.assertEqual(statut, 200)
        self.assertEqual(json.loads(corps)["messages"][1]["content"], "salut")

    def test_seule_une_liste_blanche_est_joignable_et_rien_ne_configure_l_hote(self):
        m, conv = self.preparer()
        for chemin in ("/api/reglages", "/api/acces", "/api/mettre-a-jour", "/api/nouveau-pin", "/api/memoire", "/api/travaux-ajouter", "/api/machines"):
            self.assertEqual(self.relais("POST", chemin, {"x": 1})[0], 404, chemin)
        for chemin in ("/api/etat", "/api/acces", "/api/machines", "/api/conversation?id=../../x", "/image/../x"):
            self.assertEqual(self.relais("GET", chemin)[0], 404, chemin)

    def test_le_tour_relaye_garde_les_reglages_de_l_hote(self):
        m, conv = self.preparer()
        recus = {}

        def faux_tour(c, texte, emit, r, stop, depuis, **kw):
            recus.update(texte=texte, modele=r["modele"], machine=r.get("machine"), identite=kw.get("identite"))
            emit({"type": "fin", "conversation": {"id": c["id"], "titre": c["titre"]}})
        with mock.patch("lutin.server._m.tour", faux_tour):
            statut, corps = self.relais("POST", "/api/chat", {"message": "salut", "conversation": conv["id"], "modele": "pirate:70b", "machine": "a" * 32, "options": {"auto_commandes": True, "auto_ecriture": True}})
        self.assertEqual(statut, 200, corps)
        self.assertIn('"type": "fin"', corps)
        self.assertNotEqual(recus["modele"], "pirate:70b")
        self.assertFalse(recus["machine"])
        self.assertTrue(str(recus["identite"]).startswith("machine : "))
        self.assertFalse(A.options_read(conv["id"]).get("auto_commandes"), "une machine distante n'active pas les accords automatiques")

    def test_depuis_cette_page_les_octets_passent_et_rien_n_est_garde_ici(self):
        m, conv = self.preparer()
        machines.LAST_STATE[m["id"]] = "operationnel"
        statut, corps = self.http("GET", "/h/{}/api/conversation?id={}".format(m["id"], conv["id"]))
        self.assertEqual(statut, 200, corps)
        self.assertEqual(json.loads(corps)["titre"], "Sur l'hôte")

    def test_le_tour_en_flux_traverse_la_page_et_les_erreurs_de_l_hote_aussi(self):
        m, conv = self.preparer()
        machines.LAST_STATE[m["id"]] = "operationnel"

        def faux_tour(c, texte, emit, r, stop, depuis, **kw):
            emit({"type": "texte", "texte": "voilà"})
            emit({"type": "fin", "conversation": {"id": c["id"], "titre": c["titre"]}})
        with mock.patch("lutin.server._m.tour", faux_tour):
            statut, corps = self.http("POST", "/h/{}/api/chat".format(m["id"]), {"message": "salut", "conversation": conv["id"]}, {"X-Token": A.TOKEN})
        self.assertEqual(statut, 200, corps)
        evenements = [json.loads(l) for l in corps.splitlines() if l.strip()]
        self.assertEqual([e["type"] for e in evenements], ["debut", "texte", "fin"])
        statut, corps = self.http("POST", "/h/{}/api/image".format(m["id"]), None, {"X-Token": A.TOKEN})
        self.assertEqual(statut, 400, "l'erreur de l'hôte est rendue telle quelle, pas déguisée en panne")
        machines.node_allow_control(False)
        statut, corps = self.http("GET", "/h/{}/api/conversation?id={}".format(m["id"], conv["id"]))
        self.assertEqual(statut, 403)
        self.assertIn("conversations pilotées", json.loads(corps)["erreur"])

    def test_une_machine_qui_ne_repond_pas_donne_un_message_clair(self):
        m, conv = self.preparer()
        machines.LAST_STATE[m["id"]] = "injoignable"
        statut, corps = self.http("GET", "/h/{}/api/conversation?id={}".format(m["id"], conv["id"]))
        self.assertEqual(statut, 503)
        self.assertIn("ne répond pas", json.loads(corps)["erreur"])
        self.assertEqual(self.http("GET", "/h/{}/api/conversation?id={}".format("0" * 32, conv["id"]))[0], 404)

    def test_les_conversations_proposees_exigent_le_droit_de_l_hote(self):
        m, conv = self.preparer(piloter=False)
        with self.assertRaises(PermissionError):
            machines.node_share("conversations", {})
        machines.node_allow_control(True)
        self.assertIn(conv["id"], [c["id"] for c in machines.node_share("conversations", {})["conversations"]])

    def test_les_anciennes_copies_jamais_continuees_sont_supprimees(self):
        copie = A.conv_new()
        copie.update(messages=[{"role": "user", "content": "a"}], origine={"machine": "X", "messages_importes": 1})
        A.conv_write(copie)
        continuee = A.conv_new()
        continuee.update(messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "suite"}], origine={"machine": "X", "messages_importes": 1})
        A.conv_write(continuee)
        machines.CLEANED_COPIES[0] = False
        self.assertEqual(machines.clean_imported_copies(), 1)
        ids = [c["id"] for c in A.conv_list()]
        self.assertNotIn(copie["id"], ids)
        self.assertIn(continuee["id"], ids)


class MesuresApi(Base):
    def test_la_page_lit_le_classement_et_refuse_ce_qui_n_existe_pas(self):
        statut, corps = self.http("GET", "/api/mesures-moteurs", None, {"X-Token": A.TOKEN})
        self.assertEqual(statut, 200, corps)
        vue = json.loads(corps)
        self.assertEqual(sorted(vue), ["candidats", "classement", "etat", "nombre"])
        self.assertEqual(self.http("POST", "/api/mesurer-moteur", {"moteur": "inconnu", "modele": "x"}, {"X-Token": A.TOKEN})[0], 400)


if __name__ == "__main__":
    unittest.main()
