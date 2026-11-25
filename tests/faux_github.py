"""A fake GitHub for the tests of third-party skills: repositories {owner/name: {path: content or (content, mode)}} served like the API (tree) and raw.githubusercontent.com (files)."""
import json
import urllib.request

SKILL = "---\nname: {nom}\ndescription: {desc}\nlicense: MIT\n---\n\n# {nom}\n\nFais ceci puis cela.\n"


class FauxGithub:
    """Des dépôts {propriétaire/dépôt: {chemin: contenu ou (contenu, mode)}} servis comme l'API (arbre) et raw.githubusercontent.com (fichiers)."""

    def __init__(self, depots):
        self.depots, self.appels, self.limite = depots, [], False
        self.entetes = []

    def __call__(self, url, entetes=None):
        self.appels.append(url)
        self.entetes.append(dict(entetes or {}))
        if self.limite:
            return 403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"}, b""
        if url.startswith("https://api.github.com/repos/") and "/git/trees/" in url:
            depot = "/".join(url.split("/")[4:6])
            if depot not in self.depots:
                return 404, {}, b""
            return 200, {}, json.dumps(self.arbre(depot)).encode()
        if url.startswith("https://raw.githubusercontent.com/"):
            morceaux = url.split("/")
            depot, chemin = "/".join(morceaux[3:5]), "/".join(morceaux[6:])
            contenu = self.depots.get(depot, {}).get(urllib.request.unquote(chemin))
            if contenu is None:
                return 404, {}, b""
            contenu = contenu[0] if isinstance(contenu, tuple) else contenu
            return 200, {}, contenu if isinstance(contenu, bytes) else contenu.encode("utf-8")
        if url.startswith("https://api.github.com/search/repositories"):
            return 200, {}, json.dumps({"items": [{"full_name": "a/skills-1", "stargazers_count": 12, "description": "Des skills", "pushed_at": "2026-11-01T00:00:00Z"}]}).encode()
        return 404, {}, b""

    def arbre(self, depot):
        fichiers = self.depots[depot]
        entrees, dossiers = [], {}
        for chemin, contenu in sorted(fichiers.items()):
            octets = contenu[0] if isinstance(contenu, tuple) else contenu
            mode = contenu[1] if isinstance(contenu, tuple) else "100644"
            taille = len(octets if isinstance(octets, bytes) else octets.encode("utf-8"))
            entrees.append({"path": chemin, "type": "blob", "mode": mode, "size": taille, "sha": "b%06d" % (hash(chemin) % 10 ** 6)})
            parent = chemin
            while "/" in parent:
                parent = parent.rsplit("/", 1)[0]
                dossiers.setdefault(parent, []).append((chemin, taille))
        for d, contenus in dossiers.items():
            entrees.append({"path": d, "type": "tree", "mode": "040000", "sha": "t" + str(abs(hash(tuple(contenus))) % 10 ** 8)})
        return {"sha": "racine" + str(abs(hash(tuple(sorted(fichiers)))) % 10 ** 6), "truncated": False, "tree": entrees}


def depot_type(**plus):
    d = {"skills/pdf/SKILL.md": SKILL.format(nom="pdf", desc="Travailler avec des fichiers PDF"), "skills/pdf/scripts/lire.py": "print('lit un pdf')\n", "skills/pdf/LICENSE.txt": "MIT",
         "skills/docx/SKILL.md": SKILL.format(nom="docx", desc="Créer des documents Word"), "skills/docx/references/guide.md": "# Guide\n",
         ".gemini/skills/pdf/SKILL.md": SKILL.format(nom="pdf", desc="copie"), "node_modules/x/SKILL.md": "---\nname: x\n---\n", "README.md": "# Dépôt"}
    d.update(plus)
    return d
