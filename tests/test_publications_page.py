"""L'API de GitHub limite à 60 requêtes par heure et par adresse (HTTP 403 ensuite) : Colibri, ExLlamaV3, TabbyAPI et llama.cpp lisent alors leurs versions sur les pages publiques de github.com."""
import unittest

import context  # noqa: F401
from lutin import colibri, exllamav3, miseajour  # noqa: E402
from lutin import moteur_llamacpp as ll  # noqa: E402

SHA = "c" * 40
ATOM = '<feed><entry><id>tag:github.com,2008:Repository/1/b200</id><link href="https://github.com/ggml-org/llama.cpp/releases/tag/b200"/></entry><entry><link href="https://github.com/ggml-org/llama.cpp/releases/tag/b199"/></entry><entry><link href="https://github.com/ggml-org/llama.cpp/releases/tag/v0.9.0"/></entry></feed>'
COMMITS = '<feed><entry><id>tag:github.com,2008:Grit::Commit/%s</id></entry></feed>' % SHA


def page(url):
    return '<a href="/ggml-org/llama.cpp/releases/download/%s/llama-%s-bin-win-cpu-x64.zip">x</a>' % (url.rsplit("/", 1)[1], url.rsplit("/", 1)[1])


def http_sans_api(url, entetes=None):
    """Tout ce qui passe par l'API répond 403 ; les pages publiques répondent."""
    if "api.github.com" in url:
        return 403, {}, b""
    if url.endswith("/releases/latest"):
        return 200, {"x-lutin-url-finale": "https://github.com/x/y/releases/tag/v2.1.0"}, b""
    if url.endswith("releases.atom"):
        return 200, {}, ATOM.encode()
    if "expanded_assets" in url:
        return 200, {}, (b"" if url.endswith("b200") else page(url).encode())
    if url.endswith("commits/main.atom"):
        return 200, {}, COMMITS.encode()
    return 404, {}, b""


class SansApi(unittest.TestCase):
    def test_colibri_lit_sa_version_sur_la_page_quand_l_api_refuse(self):
        self.assertEqual(colibri.derniere_version(http_sans_api), "2.1.0")

    def test_exllamav3_et_tabbyapi_aussi(self):
        self.assertEqual(exllamav3.derniere_version_lib(http_sans_api), "2.1.0")
        self.assertEqual(exllamav3.dernier_commit(http_sans_api), SHA)

    def test_sans_aucune_reponse_l_erreur_dit_la_limite_de_requetes(self):
        def mort(url, entetes=None):
            return (403, {}, b"") if "api.github.com" in url else (404, {}, b"")
        with self.assertRaises(ValueError) as e:
            colibri.derniere_version(mort)
        self.assertIn("403", str(e.exception))
        self.assertIn("limite", str(e.exception))

    def test_publications_les_plus_recentes_dont_l_etiquette_convient(self):
        rs = miseajour.publications_par_page("ggml-org/llama.cpp", r"b\d+", 4, http=http_sans_api)
        self.assertEqual([r["tag_name"] for r in rs], ["b200", "b199"], "v0.9.0 n'est pas une version à installer")
        self.assertEqual(rs[0]["assets"], [], "une publication encore vide (binaires en cours de construction) est gardée telle quelle")
        self.assertEqual(rs[1]["assets"][0]["name"], "llama-b199-bin-win-cpu-x64.zip")
        self.assertEqual(rs[1]["assets"][0]["browser_download_url"], "https://github.com/ggml-org/llama.cpp/releases/download/b199/llama-b199-bin-win-cpu-x64.zip")

    def test_llamacpp_choisit_la_plus_recente_publication_qui_a_ses_fichiers(self):
        rs = miseajour.publications_par_page("ggml-org/llama.cpp", r"b\d+", 4, http=http_sans_api)
        etiquette, assets = ll.choisir_fichiers(rs, "windows", "amd64", "cpu")
        self.assertEqual(etiquette, "b199")
        self.assertEqual(len(assets), 1)


if __name__ == "__main__":
    unittest.main()
