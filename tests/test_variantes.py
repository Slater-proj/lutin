import unittest

import context  # noqa: F401
from lutin import conseil_machine, diagnostic, variantes
from lutin.machine import Gpu, Profil


def bloc(nom, tag, taille):
    return ('<div class="group px-4 py-3"><a href="/library/{n}:{t}" class="md:hidden flex flex-col space-y-[6px] group"><div class="flex items-center font-medium">'
            '<span class="group-hover:underline">{n}:{t}</span></div><div><span><span class="font-mono"> abc123</span> &nbsp;·&nbsp; {s} &nbsp;·&nbsp; 40K context window &nbsp;·&nbsp; '
            'Text input</span></div></a><div class="hidden md:flex"><a href="/library/{n}:{t}" class="group-hover:underline">{n}:{t}</a></div></div>').format(n=nom, t=tag, s=taille)


PAGE = "".join([bloc("qwen3", "8b", "5.2GB"), bloc("qwen3", "8b-q4_K_M", "5.2GB"), bloc("qwen3", "8b-q8_0", "8.9GB"), bloc("qwen3", "8b-fp16", "16GB"),
                bloc("qwen3", "8b-instruct-2507", "5.0GB"), bloc("qwen3", "4b", "2.5GB"), bloc("qwen3", "4b-q8_0", "4.4GB"), bloc("qwen3", "4b-q4_K_M", "2.6GB"),
                bloc("qwen3", "0.6b-q8_0", "639MB"), bloc("autre", "8b-q8_0", "9GB")])


class Lecture(unittest.TestCase):
    def test_variantes_d_un_modele(self):
        r = variantes.analyser(PAGE, "qwen3", "8b")
        self.assertEqual(r["defaut"], {"id": "qwen3:8b", "go": 5.2})
        self.assertEqual([(v["precision"], v["go"], v["defaut"]) for v in r["variantes"]], [("q4_K_M", 5.2, True), ("q8_0", 8.9, False), ("fp16", 16.0, False)],
                         "triées par taille ; « instruct-2507 » n'est pas une précision ; l'autre modèle est ignoré")
        self.assertEqual(r["variantes"][1]["id"], "qwen3:8b-q8_0")

    def test_la_variante_par_defaut_tolere_un_petit_ecart_d_arrondi(self):
        r = variantes.analyser(PAGE, "qwen3", "4b")
        self.assertTrue(next(v for v in r["variantes"] if v["precision"] == "q4_K_M")["defaut"], "2,5 contre 2,6 Go : c'est la même")
        self.assertFalse(next(v for v in r["variantes"] if v["precision"] == "q8_0")["defaut"])

    def test_page_meconnaissable_ou_sans_variantes(self):
        self.assertEqual(variantes.analyser("<html>rien</html>", "qwen3", "8b"), {"defaut": None, "variantes": []})
        self.assertEqual(variantes.analyser(None, "qwen3", "8b"), {"defaut": None, "variantes": []})

    def test_megaoctets(self):
        r = variantes.analyser(PAGE, "qwen3", "0.6b")
        self.assertEqual(r["variantes"][0]["go"], 0.64)

    def test_lister_utilise_le_cache_et_refuse_les_noms_sans_taille_ou_deja_precis(self):
        variantes.CACHE.clear()
        appels = []

        def http(url):
            appels.append(url)
            return 200, {}, PAGE.encode("utf-8")
        self.assertEqual(len(variantes.lister("qwen3:8b", http=http)["variantes"]), 3)
        variantes.lister("qwen3:4b", http=http)
        self.assertEqual(appels, ["https://ollama.com/library/qwen3/tags"], "une seule lecture par modèle")
        for mauvais in ("qwen3", "qwen3:8b-q8_0", "huihui_ai/qwen3-abliterated:4b", "", "qwen3:8b:q8"):
            with self.assertRaises(ValueError, msg=mauvais):
                variantes.lister(mauvais, http=http)
        variantes.CACHE.clear()
        with self.assertRaises(OSError):
            variantes.lister("qwen3:8b", http=lambda u: (500, {}, b""))
        with self.assertRaises(OSError):
            variantes.lister("zzz:8b", http=lambda u: (200, {}, PAGE.encode("utf-8")))
        variantes.CACHE.clear()

    def test_chaque_precision_a_son_explication(self):
        for p in ("q4_K_M", "q5_K_M", "q6_K", "q8_0", "fp16", "q3_K_S"):
            self.assertTrue(variantes.decrire(p).endswith("."), p)
        self.assertNotEqual(variantes.decrire("q4_K_M"), variantes.decrire("q8_0"))


CPU = Profil(systeme="linux", ram_go=32.0, ram_libre_go=13.0, gpus=[])
GROS = Profil(systeme="linux", ram_go=64.0, ram_libre_go=40.0, gpus=[Gpu("RTX", "nvidia", 24)])


class ConseilMachine(unittest.TestCase):
    def test_machine_sans_carte_graphique(self):
        c = conseil_machine.conseils(CPU, {"num_ctx": 24576, "reflexion": True})
        self.assertEqual({x["cle"]: x["conseille"] for x in c}, {"num_ctx": 12288, "reflexion": False})
        self.assertEqual(conseil_machine.appliquer(CPU, {"num_ctx": 24576, "reflexion": True}), {"num_ctx": 12288, "reflexion": False})

    def test_rien_a_conseiller_quand_les_reglages_conviennent_ou_que_la_machine_est_grosse(self):
        self.assertEqual(conseil_machine.conseils(CPU, {"num_ctx": 8192, "reflexion": False}), [])
        self.assertEqual(conseil_machine.conseils(GROS, {"num_ctx": 24576, "reflexion": True}), [])
        self.assertEqual(conseil_machine.conseils(None, {"num_ctx": 24576}), [])
        self.assertEqual(conseil_machine.appliquer(GROS, {"num_ctx": 24576}), {})
        self.assertEqual([x["cle"] for x in conseil_machine.conseils(CPU, {"num_ctx": 8192, "reflexion": True})], ["reflexion"], "un seul réglage à changer")

    def test_le_conseil_apparait_dans_le_diagnostic_sans_masquer_une_erreur_et_se_laisse_ignorer(self):
        c = conseil_machine.conseils(CPU, {"num_ctx": 24576, "reflexion": True})
        base = dict(ollama_actif=True, ollama_installe=True, installes=["qwen3:4b"], docker=False, conseils=c)
        p, = diagnostic.diagnostiquer(reglages={"modele": "qwen3:4b", "conseil_machine": True}, **base)
        self.assertEqual((p["code"], p["niveau"], p["action"]["type"], p["action2"]["type"]), ("petite_machine", "info", "appliquer_conseil", "ignorer_conseil"))
        self.assertEqual(diagnostic.diagnostiquer(reglages={"modele": "qwen3:4b", "conseil_machine": False}, **base), [], "ignoré")
        erreurs = diagnostic.diagnostiquer(reglages={"modele": "qwen3:4b"}, **dict(base, installes=[]))
        self.assertEqual([e["code"] for e in erreurs], ["aucun_modele"], "une vraie panne passe avant le conseil")
        self.assertEqual(diagnostic.diagnostiquer(reglages={"modele": "qwen3:4b"}, **dict(base, conseils=[])), [])


if __name__ == "__main__":
    unittest.main()
