"""Le serveur HTTP de Lutin : le gestionnaire de requêtes (pages, API JSON, flux de la conversation). L'état et les fonctions métier restent dans moteur ; ce module les atteint par « _m.NOM » (lu à chaque appel)."""
from http.server import BaseHTTPRequestHandler
from . import bench as _bench
from . import acces as _acces
from . import adequation as _adequation
from . import conseil as _conseil
from . import emplacements as _emplacements
from . import decouverte as _decouverte
from . import donnees as _donnees
from . import horsligne as _hl
from . import modes as _modes
from . import pieces as _pieces
from . import images as _images
from . import addons as _addons
from . import fond as _fond
from . import planifie as _plan
from . import rappel as _rappel
from . import suivi as _suivi
from . import i18n as _i18n
from . import projet_claude as _pc
from . import sauvegarde as _sauv
from . import securite as _sec
from .i18n import t as _t
from datetime import datetime
import hmac
import io
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from . import moteur as _m


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "Lutin/" + _m.VERSION

    def log_message(self, fmt, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, TimeoutError):          # la page a été fermée ou rechargée pendant la réponse : sans importance
            pass

    def _envoyer(self, code, corps, type_="application/json; charset=utf-8", en_tetes=None):
        if isinstance(corps, dict) and _i18n.langue() != "fr":
            corps = _m.traduire_json(corps)
        donnees = corps if isinstance(corps, (bytes, bytearray)) else (corps if isinstance(corps, str) else json.dumps(corps, ensure_ascii=False)).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(donnees)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (en_tetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(donnees)

    # ---- sécurité (voir lutin.securite) ----
    def _local(self):
        """La requête vient de cette machine : la boucle locale, ou l'adresse de la machine sur le réseau local (un navigateur d'ici qui ouvre http://192.168.x.y:8777 arrive avec cette adresse-là).
        Une autre machine ne peut pas se faire passer pour elle : la connexion TCP n'aboutirait pas."""
        ip = self.client_address[0]
        return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1") or bool(_m.IP_LAN and ip == _m.IP_LAN)

    def _jeton_valide(self):
        donne = self.headers.get("X-Token") or ""
        return any(hmac.compare_digest(donne, attendu) for attendu in (_m.JETON, _m.JETON_CONSOLE))

    def _authentifie(self):
        if self._local() and hmac.compare_digest(self.headers.get("X-Token") or "", _m.JETON_CONSOLE):
            return True                                      # la console de cette machine (fichier réservé à l'utilisateur)
        return _sec.acces(_m.SECURITE, _m.APPAREILS, self.client_address[0], self.headers)[0]

    def _identite(self):
        """Qui fait cette requête, pour le journal : « console », « local », le nom donné par le proxy, ou « appareil »."""
        if self._local() and hmac.compare_digest(self.headers.get("X-Token") or "", _m.JETON_CONSOLE):
            return "console"
        return _sec.acces(_m.SECURITE, _m.APPAREILS, self.client_address[0], self.headers)[1]

    def _sur_cette_machine(self):
        """Le navigateur est sur cette machine : connexion de boucle locale, nom d'hôte de boucle locale, et aucun en-tête laissant croire qu'un relais (proxy, tunnel) a transmis une requête venue d'ailleurs."""
        relais = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "Via", "X-Real-IP")
        return self._local() and not any(self.headers.get(h) for h in relais) and (_sec._est_boucle(_sec._sans_port(self.headers.get("Host") or "")) or bool(_m.IP_LAN and _sec._sans_port(self.headers.get("Host") or "") == _m.IP_LAN))

    def _configurateur(self):
        """Peut-on changer ce qui ouvre ou modifie la machine (dossiers de travail, niveau d'accès, restauration) ? Seulement depuis cette machine : au niveau « machine seulement », avec le jeton de la console,
        ou — au niveau « réseau » — depuis le navigateur de cette machine (jamais depuis un appareil appairé). Derrière un proxy, la commande lutin seulement : le proxy est sur la machine, il ne prouve rien."""
        if _m.SECURITE.niveau == _sec.LOCAL:
            return True
        if self._local() and hmac.compare_digest(self.headers.get("X-Token") or "", _m.JETON_CONSOLE):
            return True
        return _m.SECURITE.niveau == _sec.RESEAU and self._sur_cette_machine()

    def _controle(self, ecriture):
        """Nom d'hôte (contre le « DNS rebinding ») et origine (contre les requêtes venues d'autres sites). Répond lui-même en cas de refus."""
        if not _sec.hote_autorise(_m.SECURITE, self.headers.get("Host"), _m.IP_LAN):
            self._envoyer(403, {"erreur": "nom d'hôte non autorisé"})
            return False
        if ecriture and not _sec.origine_autorisee(_m.SECURITE, self.headers.get("Origin"), self.headers.get("Host"), _m.IP_LAN):
            self._envoyer(403, {"erreur": "origine non autorisée"})
            return False
        return True

    def _page_connexion(self):
        page = _m.PAGE_CONNEXION
        if _i18n.langue() != "fr":
            for phrase in _m.TEXTES_PAGE_CONNEXION:
                page = page.replace(phrase, _t(phrase))
            page = page.replace('<html lang="fr">', '<html lang="{}">'.format(_i18n.langue()))
        return self._envoyer(200, page, "text/html; charset=utf-8")

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if not self._controle(False):
            return
        if chemin in ("/", "/index.html") and not self._authentifie():
            return self._page_connexion()
        if chemin.startswith("/api/"):
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            if not self._jeton_valide():
                return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        if chemin.startswith("/image/"):                       # hors /api/ : la balise <img> envoie le cookie de session, pas le jeton de la page
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                octets, mime = _images.lire(chemin[len("/image/"):])
            except ValueError:
                return self._envoyer(404, {"erreur": _t("Image inconnue.")})
            return self._envoyer(200, octets, mime, {"Content-Security-Policy": "default-src 'none'; sandbox"})
        if chemin in ("/", "/index.html"):
            return self._envoyer(200, _m.page_web(), "text/html; charset=utf-8")
        if chemin == "/api/etat":
            o = _m.etat_ollama()
            r = _m.reglages()
            modeles = _m.modeles_connus(o["installes"], o.get("tailles"))
            profil = _adequation.profil_pret()
            return self._envoyer(200, {"adequation": _adequation.pour_la_liste(modeles, profil, _m._CATALOGUE["modeles"]), "machine": profil.resume() if profil else "", "budget_go": profil.budget_go() if profil else 0,
                                       "familles": {k: _t(v) for k, v in (_m._CATALOGUE.get("familles") or {}).items()}, "disque_modeles": _emplacements.jauge_modeles(),
                                       "version": _m.VERSION, "ollama": o["actif"], "ollama_installe": bool(_m.chemin_ollama()), "installes": o["installes"], "modeles": modeles, "modeles_masques": len(_m.lire_registre_modeles()["masques"]), "actives": list(_m.TOURS_ACTIFS),
                                       "pulls": _m.PULLS, "reglages": r, "conversations": _m.conv_liste(), "racine": str(_m.RACINE), "donnees": str(_m.DONNEES),
                                       "outil": bool(self._outil_vivant()), "hors_ligne": _hl.actif(), "niveau": _m.SECURITE.niveau, "langue": _i18n.langue(), "langue_reglage": _i18n.langue_configuree(), "cpus": os.cpu_count() or 1, "redemarrage": {"necessaire": _acces.securite_enregistree() != _m.SECURITE, "possible": _acces.peut_redemarrer()}, "nouvelle_version": _m.nouvelle_version_lutin(), "travaux": _m.travaux_etat(), "configurateur": self._configurateur(), "addons_alertes": _addons.alertes(),
                                       "bench": {"en_cours": _m.BENCH["en_cours"], "etape": _m.BENCH["etape"], "erreur": _m.BENCH["erreur"], "mesures": _bench.lire(_m.chemin_bench())}, "attentes": [{"id": a.id, "titre": a.titre, "detail": a.detail, "diff": a.diff} for a in _m.Attente.EN_COURS.values()]})
        if chemin == "/api/conseil":
            r = _m.reglages()
            vitesse = ((_bench.lire(_m.chemin_bench()).get(r["modele"]) or {}).get("resultats") or {}).get("vitesse")
            if not vitesse or not vitesse.get("tok_s"):
                return self._envoyer(200, {"mesure": None, "conseil": []})
            from .machine import detecter
            return self._envoyer(200, {"mesure": vitesse, "conseil": _conseil.analyser(vitesse, detecter(), r, _m._CATALOGUE, _m.etat_ollama()["installes"], _m.ps_modele(r["modele"]))})
        if chemin == "/api/planifie":
            return self._envoyer(200, _plan.etat())
        if chemin == "/api/documents":
            return self._envoyer(200, _rappel.etat_documents())
        if chemin == "/api/documents-chercher":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            requete = (q.get("q") or [""])[0][:300]
            if not _rappel.mots(requete):
                return self._envoyer(400, {"erreur": _t("Requête vide ou trop vague : donne quelques mots-clés.")})
            return self._envoyer(200, {"passages": _rappel.chercher_documents(requete)})
        if chemin == "/api/notes":
            return self._envoyer(200, {"notes": _donnees.lister_notes()})
        if chemin == "/api/acces":
            return self._envoyer(200, _acces.etat(self._configurateur()))
        if chemin == "/api/qr":
            texte = urllib.parse.unquote(self.path.split("d=", 1)[1]) if "d=" in self.path else ""
            try:
                return self._envoyer(200, _acces.qr_json(texte))
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/commande-claude":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                return self._envoyer(200, {"texte": _pc.commande(_m.RACINE, (q.get("nom") or [""])[0], (q.get("args") or [""])[0][:2000])})
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/projet-claude":
            d = _pc.detecter(_m.RACINE)
            return self._envoyer(200, {"detecte": d, "resume": _pc.resume(d) if not _pc.est_vide(d) else "", "racine": str(_m.RACINE)})
        if chemin == "/api/travaux":
            return self._envoyer(200, dict(_m.travaux_etat(), modifiable=self._configurateur()))
        if chemin == "/api/dossiers":                          # le navigateur de dossiers de la page : seulement pour qui peut gérer les dossiers de travail (cette machine)
            if not self._configurateur():
                return self._envoyer(403, {"erreur": _t("Les dossiers se parcourent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                return self._envoyer(200, _m.lister_dossiers((q.get("chemin") or [""])[0]))
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/decouvrir":                           # la bibliothèque d'Ollama (nouveautés, populaires, recherche)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                return self._envoyer(200, _decouverte.chercher((q.get("q") or [""])[0], (q.get("o") or ["newest"])[0], (q.get("p") or ["1"])[0]))
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
            except OSError as e:
                return self._envoyer(503, {"erreur": str(e)})
        if chemin == "/api/suivi":                               # la fiche de suivi d'une conversation (affichée, modifiable)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            ident = (q.get("conversation") or [""])[0]
            try:
                conv = _m.conv_lire(ident)
                r = _m.reglages()
                sections = _suivi.lire(ident)
                return self._envoyer(200, {"sections": sections, "texte": _suivi.serialiser(ident, sections), "mesure": _suivi.mesure(ident, r["num_ctx"]), "mode": _m.memoire_longue(conv, r),
                                           "mode_general": r["memoire_longue"], "chemin": str(_suivi.chemin(ident))})
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/addons":                              # les addons : état, réglages (jamais les secrets), dernière vérification
            return self._envoyer(200, {"liste": _addons.liste(), "alertes": _addons.alertes()})
        if chemin == "/api/fond":                                # le travail de fond : travaux et avancement
            return self._envoyer(200, {"liste": _fond.liste()})
        if chemin == "/api/fond-rapport":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                return self._envoyer(200, {"texte": _fond.rapport(_fond.trouver((q.get("id") or [""])[0]))})
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/mettre-a-jour-etat":
            return self._envoyer(200, _acces.etat_maj())
        if chemin == "/api/dossier-modeles-etat":
            return self._envoyer(200, _emplacements.etat_copie())
        if chemin == "/api/emplacements":                        # tous les dossiers que Lutin utilise, leur taille et la place libre
            from . import emplacements
            return self._envoyer(200, dict(emplacements.lister(), modifiable=self._configurateur()))
        if chemin == "/api/journal":
            m = re.search(r"[?&]n=(\d+)", self.path)
            return self._envoyer(200, {"entrees": _m.lire_journal(int(m.group(1)) if m else 200)})
        if chemin == "/api/sauvegarde":
            tampon = io.BytesIO()
            c = _m.chemin_config()
            try:
                _sauv.exporter({"config": c.parent if c else None, "donnees": _m.DONNEES, "memoire": _m.MEMOIRE}, tampon)
            except _sauv.ErreurSauvegarde as e:
                return self._envoyer(400, {"erreur": str(e)})
            return self._envoyer(200, tampon.getvalue(), "application/zip", {"Content-Disposition": 'attachment; filename="lutin-sauvegarde-{}.zip"'.format(datetime.now().strftime("%Y%m%d-%H%M%S"))})
        if chemin == "/api/propositions":
            return self._envoyer(200, _m.lire_propositions())
        if chemin == "/api/sante-systeme":
            return self._envoyer(200, _m.etat_sante())
        if chemin == "/api/git":
            return self._envoyer(200, _m.git_etat())
        if chemin == "/api/revue":
            try:
                return self._envoyer(200, _m.revue_tour((re.search(r"id=([0-9a-f]+)", self.path) or [None, ""])[1]))
            except ValueError as erreur:
                return self._envoyer(404, {"erreur": str(erreur)})
        if chemin == "/api/recherche":
            return self._envoyer(200, _m.chercher_conversations(urllib.parse.unquote_plus(self.path.split("q=", 1)[1]) if "q=" in self.path else ""))
        if chemin == "/api/contexte":
            try:
                ident = (re.search(r"id=([0-9a-f]+)", self.path) or [None, ""])[1]
                return self._envoyer(200, _m.jauge_contexte(_m.conv_lire(ident)))
            except ValueError as erreur:
                return self._envoyer(404, {"erreur": str(erreur)})
        if chemin in ("/manifest.webmanifest", "/icone.svg", "/logo.svg") or re.match(r"^/icone-(180|192|512)\.png$", chemin):
            return self._statique_pwa(chemin)
        if chemin == "/api/memoire":
            return self._envoyer(200, {"CONTEXTE.md": _m.lire_memoire("CONTEXTE.md"), "MEMOIRE.md": _m.lire_memoire("MEMOIRE.md")})
        if chemin == "/api/skills":
            liste = [{"nom": n, "titre": t} for n, t in _m.lister_skills()]
            return self._envoyer(200, {"skills": liste})
        if chemin.startswith("/api/skills/"):
            nom = urllib.parse.unquote(chemin[len("/api/skills/"):])
            try:
                return self._envoyer(200, {"nom": nom, "texte": _m.lire_skill(nom)})
            except (OSError, ValueError) as erreur:
                return self._envoyer(404, {"erreur": str(erreur)})
        if chemin == "/api/conversation":
            try:
                ident = (re.search(r"id=([0-9a-f]+)", self.path) or [None, ""])[1]
                return self._envoyer(200, _m.conv_lire(ident))
            except ValueError as erreur:
                return self._envoyer(404, {"erreur": str(erreur)})
        # Fichiers statiques (lib/)
        if chemin.startswith("/lib/"):
            nom = chemin[5:]  # retire "/lib/"
            base = (_m.WEB / "lib").resolve()
            if not nom or ":" in nom or "\\" in nom or nom.startswith("/") or ".." in nom:          # avant tout accès disque (un chemin réseau ferait contacter une autre machine)
                return self._envoyer(403, {"erreur": "interdit"})
            try:
                # Un chemin absolu (« C:/... », « \\serveur\... ») remplacerait le dossier lib/ dans la jointure : on vérifie le résultat final.
                fichier = (base / nom).resolve()
                dedans = fichier == base or base in fichier.parents
            except (OSError, ValueError):
                dedans = False
            if not dedans:
                return self._envoyer(403, {"erreur": "interdit"})
            if fichier.is_file():
                contenu = fichier.read_bytes()
                mime = "application/javascript" if nom.endswith(".js") else "text/css" if nom.endswith(".css") else "application/octet-stream"
                return self._envoyer(200, contenu, mime)
        return self._envoyer(404, {"erreur": "introuvable"})

    def _statique_pwa(self, chemin):
        """Manifeste et icônes pour « Ajouter à l'écran d'accueil » (téléphone). Les icônes sont dessinées par le serveur : aucun fichier image à fournir."""
        if chemin == "/manifest.webmanifest":
            manifeste = {"name": "Lutin", "short_name": "Lutin", "description": "Assistant IA local", "start_url": "/", "scope": "/", "display": "standalone",
                         "background_color": "#0b0f14", "theme_color": "#0b0f14",
                         "icons": [{"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"}, {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}]}
            return self._envoyer(200, manifeste, "application/manifest+json; charset=utf-8")
        if chemin in ("/icone.svg", "/logo.svg"):
            return self._envoyer(200, _m.ICONE_SVG, "image/svg+xml; charset=utf-8")
        return self._envoyer(200, _m.icone_png(int(re.search(r"(\d+)", chemin).group(1))), "image/png")

    @staticmethod
    def _outil_vivant():
        if not _m.OUTIL:
            return False
        try:
            with urllib.request.urlopen(_m.OUTIL + "/api/sante", timeout=1.5):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _taille_corps(self):
        """La taille annoncée du corps de la requête : un nombre positif ou nul ; une valeur absurde (négative ou pas un nombre) vaut « trop gros », jamais une lecture sans fin."""
        brut = str(self.headers.get("Content-Length") or "0").strip()
        return int(brut) if brut.isascii() and brut.isdigit() else 1 << 40

    def _restaurer(self):
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        if not self._configurateur():
            return self._envoyer(403, {"erreur": _t("Une sauvegarde se restaure depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin restaurer.")})
        try:
            return self._envoyer(200, _acces.restaurer_flux(self.rfile, self._taille_corps()))
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def _image(self):
        """Une image jointe : corps brut (le type est reconnu au contenu), au plus 8 Mo."""
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        taille = self._taille_corps()
        if taille > _images.TAILLE_MAX:
            return self._envoyer(413, {"erreur": _t("Image trop grosse ({} Mo au plus).").format(_images.TAILLE_MAX // (1024 * 1024))})
        try:
            return self._envoyer(200, {"id": _images.enregistrer(self.rfile.read(taille))})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def _document(self):
        """Un document ou fichier texte joint : corps brut, nom dans l'en-tête X-Nom (encodé en URL), au plus 20 Mo ; le texte est extrait tout de suite."""
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        taille = self._taille_corps()
        if taille > _pieces.TAILLE_MAX:
            return self._envoyer(413, {"erreur": _t("Fichier trop gros ({} Mo au plus).").format(_pieces.TAILLE_MAX // (1024 * 1024))})
        try:
            ident, nom, caracteres = _pieces.enregistrer(self.rfile.read(taille), urllib.parse.unquote(self.headers.get("X-Nom") or ""))
            return self._envoyer(200, {"id": ident, "nom": nom, "caracteres": caracteres})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def do_POST(self):
        if not self._controle(True):
            return
        if self.path == "/api/image":
            return self._image()
        if self.path == "/api/document":
            return self._document()
        if self.path == "/api/restaurer":                      # une archive .zip : corps brut, plus gros qu'un message
            return self._restaurer()
        taille = self._taille_corps()
        if taille > 2_000_000:
            return self._envoyer(413, {"erreur": "message trop gros"})
        try:
            donnees = json.loads(self.rfile.read(taille) or b"{}")
        except ValueError:
            return self._envoyer(400, {"erreur": "JSON invalide"})
        if self.path == "/api/appairer":                      # le seul POST sans authentification : il sert justement à en obtenir une
            return self._appairer(donnees)
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        try:
            if self.path == "/api/notes-ajouter":
                try:
                    _donnees.noter(str(donnees.get("texte", "")))
                except _m.ErreurOutil as e:
                    raise ValueError(str(e)) from e
                return self._envoyer(200, {"notes": _donnees.lister_notes()})
            if self.path == "/api/notes-supprimer":
                _donnees.supprimer_note(str(donnees.get("ligne", "")))
                return self._envoyer(200, {"notes": _donnees.lister_notes()})
            if self.path == "/api/acces":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Le niveau d'accès ne se change que depuis cette machine.")})
                return self._envoyer(200, _acces.appliquer(donnees, True))
            if self.path == "/api/mettre-a-jour":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("La mise à jour se lance depuis cette machine (ou avec la commande lutin update).")})
                return self._envoyer(200, _acces.mettre_a_jour())
            if self.path == "/api/redemarrer":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Le redémarrage se demande depuis cette machine.")})
                return self._envoyer(200, _acces.redemarrer())
            if self.path == "/api/nouveau-pin":
                if not self._local():
                    return self._envoyer(403, {"erreur": "le code ne se demande que depuis cette machine"})
                return self._envoyer(200, {"pin": _m.APPAREILS.nouveau_pin(), "valable_s": _sec.DUREE_PIN_S})
            if self.path == "/api/appareils":
                return self._envoyer(200, {"appareils": _m.APPAREILS.liste(), "niveau": _m.SECURITE.niveau})
            if self.path == "/api/appareils-revoquer":
                return self._envoyer(200, {"revoques": _m.APPAREILS.revoquer(donnees.get("id") or None)})
            if self.path == "/api/chat":
                return self._chat(donnees)
            if self.path == "/api/autotest":
                return self._envoyer(200, _m.lancer_autotest(bool(donnees.get("profond"))))
            if self.path == "/api/annuler-tour":
                return self._envoyer(200, _m.annuler_tour(str(donnees.get("conversation", ""))))
            if self.path == "/api/annuler-fichier":
                return self._envoyer(200, _m.annuler_tour(str(donnees.get("conversation", "")), str(donnees.get("chemin", ""))))
            if self.path == "/api/epingler":
                return self._envoyer(200, _m.epingler_conversation(str(donnees.get("id", "")), donnees.get("epingle")))
            if self.path == "/api/git-message":
                return self._envoyer(200, _m.git_message(donnees.get("fichiers")))
            if self.path == "/api/git-commit":
                return self._envoyer(200, _m.git_commit(donnees.get("message"), donnees.get("fichiers")))
            if self.path == "/api/memoire-choix":                                   # réponse à la question « fiche de suivi ou résumé ? » (le tour est en attente, donc pas de verrou)
                if not _m.repondre_choix_memoire(str(donnees.get("conversation", "")), str(donnees.get("choix", "")), donnees.get("garder")):
                    return self._envoyer(409, {"erreur": _t("Plus de question en attente pour cette conversation.")})
                return self._envoyer(200, {"ok": True})
            if self.path in ("/api/suivi", "/api/suivi-vider", "/api/memoire-conversation"):
                ident = str(donnees.get("conversation", ""))
                with _m.VERROU_TOURS:
                    if ident in _m.TOURS_ACTIFS:
                        return self._envoyer(409, {"erreur": _t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")})
                conv = _m.conv_lire(ident)
                r = _m.reglages()
                amorce = 0
                if self.path == "/api/suivi":
                    _suivi.ecrire(ident, _suivi.analyser(str(donnees.get("texte", ""))[:20000]))
                elif self.path == "/api/suivi-vider":
                    _suivi.supprimer(ident)
                else:
                    choix = str(donnees.get("mode", ""))
                    if choix not in ("", "resume", "fichier"):
                        raise ValueError(_t("Mémoire des longues conversations inconnue (resume ou fichier)."))
                    if choix:
                        conv["memoire_longue"] = choix
                    else:
                        conv.pop("memoire_longue", None)
                    conv.pop("memoire_provisoire", None)
                    amorce = _m.amorcer_fiche(conv, r) if choix == "fichier" else 0          # une fiche vide est remplie à partir du début de la conversation
                    _m.conv_ecrire(conv)
                return self._envoyer(200, {"mode": _m.memoire_longue(_m.conv_lire(ident), r), "mesure": _suivi.mesure(ident, r["num_ctx"]), "amorce": amorce})
            if self.path in ("/api/addon-activer", "/api/addon-reglages", "/api/addon-verifier", "/api/addon-correction", "/api/addon-flux", "/api/addon-flux-restaurer", "/api/fond-creer", "/api/fond-action"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Les extensions se gèrent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                try:
                    if self.path == "/api/addon-activer":
                        return self._envoyer(200, _addons.activer(str(donnees.get("id", "")), bool(donnees.get("actif"))))
                    if self.path == "/api/addon-reglages":
                        return self._envoyer(200, _addons.enregistrer_reglages(str(donnees.get("id", "")), donnees.get("reglages") if isinstance(donnees.get("reglages"), dict) else {}))
                    if self.path == "/api/addon-verifier":
                        return self._envoyer(200, _addons.verifier(str(donnees.get("id", ""))))
                    if self.path == "/api/addon-correction":
                        return self._envoyer(200, _addons.proposer_correction(str(donnees.get("id", ""))))
                    if self.path == "/api/addon-flux":
                        return self._envoyer(200, _addons.appliquer_flux(str(donnees.get("id", "")), donnees.get("flux")))
                    if self.path == "/api/addon-flux-restaurer":
                        return self._envoyer(200, _addons.restaurer_flux(str(donnees.get("id", ""))))
                    if self.path == "/api/fond-creer":
                        return self._envoyer(200, _fond.creer(donnees.get("nom"), donnees.get("dossier"), donnees.get("motifs"), donnees.get("consigne"), bool(donnees.get("regulier")), donnees.get("intervalle_h", 24)))
                    return self._envoyer(200, _fond.action(str(donnees.get("id", "")), str(donnees.get("action", ""))))
                except (_addons.ErreurAddon, ValueError) as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path == "/api/travaux-apercu":
                return self._envoyer(200, _m.apercu_travail(str(donnees.get("id", ""))))
            if self.path in ("/api/dossier-modeles-analyse", "/api/dossier-modeles-copie", "/api/redemarrer-ollama"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Le dossier des modèles se change depuis cette machine.")})
                from . import emplacements
                if self.path == "/api/dossier-modeles-analyse":
                    return self._envoyer(200, emplacements.analyse_dossier(str(donnees.get("chemin", ""))))
                if self.path == "/api/dossier-modeles-copie":
                    return self._envoyer(200, emplacements.copier_modeles(str(donnees.get("chemin", ""))))
                return self._envoyer(200, {"message": _m.redemarrer_ollama()})
            if self.path == "/api/dossier-modeles":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Le dossier des modèles se change depuis cette machine.")})
                from . import emplacements
                return self._envoyer(200, {"dossier": str(emplacements.definir_dossier_modeles(str(donnees.get("chemin", "")))), "note": _t("Les modèles déjà téléchargés ne sont pas déplacés : déplace-les à la main dans le nouveau dossier, ou retélécharge-les. Redémarre Ollama (quitte-le puis relance-le) pour qu'il utilise le nouveau dossier.")})
            if self.path == "/api/travaux-choisir":
                return self._envoyer(200, _m.choisir_travail(str(donnees.get("id", ""))))
            if self.path in ("/api/travaux-ajouter", "/api/travaux-retirer", "/api/travaux-deplacer", "/api/travaux-chemin"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": "Les dossiers de travail se gèrent depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin travaux."})
                if self.path == "/api/travaux-ajouter":
                    return self._envoyer(200, _m.ajouter_travail(str(donnees.get("chemin", "")), str(donnees.get("nom", ""))))
                if self.path == "/api/travaux-deplacer":
                    return self._envoyer(200, _m.deplacer_travail(str(donnees.get("id", "")), str(donnees.get("parent", "")), str(donnees.get("nom", ""))))
                if self.path == "/api/travaux-chemin":
                    return self._envoyer(200, _m.changer_chemin_travail(str(donnees.get("id", "")), str(donnees.get("chemin", ""))))
                return self._envoyer(200, _m.retirer_travail(str(donnees.get("id", "")), bool(donnees.get("nettoyer"))))
            if self.path in ("/api/reprise-detecter", "/api/reprise"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("La reprise des données d'un autre assistant se fait depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin reprendre.")})
                if self.path == "/api/reprise-detecter":
                    return self._envoyer(200, _m.reprise_detecter(str(donnees.get("chemin", "")), str(donnees.get("dossier_skills", ""))))
                return self._envoyer(200, _m.reprise_importer(str(donnees.get("chemin", "")), [str(c) for c in (donnees.get("choix") or [])], str(donnees.get("dossier_skills", "")), bool(donnees.get("ecraser")), str(donnees.get("cible", ""))))
            if self.path == "/api/importer-claude":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Un projet Claude s'importe depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin importer.")})
                return self._envoyer(200, _m.importer_projet_claude(str(donnees.get("chemin", "")), str(donnees.get("mode", "")), str(donnees.get("vers", "")), str(donnees.get("nom", ""))))
            if self.path in ("/api/planifie-ajouter", "/api/planifie-supprimer", "/api/planifie-activer", "/api/planifie-lancer"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Les tâches planifiées se gèrent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                ident = str(donnees.get("id", ""))
                if self.path == "/api/planifie-ajouter":
                    return self._envoyer(200, _plan.ajouter(donnees.get("nom"), donnees.get("prompt"), donnees.get("heure"), donnees.get("jours"), donnees.get("travail")))
                if self.path == "/api/planifie-supprimer":
                    return self._envoyer(200, _plan.supprimer(ident))
                if self.path == "/api/planifie-activer":
                    return self._envoyer(200, _plan.modifier(ident, actif=bool(donnees.get("actif"))))
                if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
                    raise ValueError(_t("Une réponse est déjà en cours : attends sa fin."))
                threading.Thread(target=lambda: _plan.executer(ident), daemon=True, name="planifie-lancer").start()
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/bench":
                return self._envoyer(200, _m.lancer_bench(str(donnees.get("modele", "")), bool(donnees.get("rapide"))))
            if self.path == "/api/version-ignorer":
                chemin = os.environ.get("LUTIN_VERSION_CACHE")
                if not chemin:
                    raise ValueError("Pas de vérification de version dans ce mode de lancement.")
                from . import miseajour
                miseajour.ignorer_version(chemin, str(donnees.get("version", ""))[:40])
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/verifier-lutin":                    # bouton « Vérifier les mises à jour » : une requête GitHub, tout de suite
                chemin = os.environ.get("LUTIN_VERSION_CACHE")
                if not chemin:
                    return self._envoyer(400, {"erreur": _t("Pas de vérification de version dans ce mode de lancement.")})
                from . import miseajour
                avant = miseajour.lire_fichier_version(chemin).get("date") or 0
                d = miseajour.verifier_lutin({"cache": str(Path(chemin).parent)}, force=True)
                if (d.get("date") or 0) <= avant:
                    return self._envoyer(503, {"erreur": _t("Impossible de joindre GitHub : {}").format(d.get("erreur") or "?"), "actuelle": _m.VERSION})
                return self._envoyer(200, {"actuelle": _m.VERSION, "derniere": miseajour.lire_fichier_version(chemin).get("version", ""), "nouvelle": _m.nouvelle_version_lutin()})
            if self.path == "/api/langue":
                try:
                    return self._envoyer(200, {"langue": _i18n.definir(str(donnees.get("valeur", "")).strip().lower())})
                except ValueError:
                    raise ValueError("Langue inconnue (fr, en ou auto).")
            if self.path == "/api/hors-ligne":
                voulu = bool(donnees.get("actif"))
                if not voulu and not (_m.SECURITE.niveau == _sec.LOCAL or self._local()):
                    return self._envoyer(403, {"erreur": "Le mode hors ligne ne se coupe que depuis cette machine."})
                return self._envoyer(200, {"hors_ligne": _hl.definir(voulu)})
            if self.path == "/api/modeles-verifier":
                if _m.VERIFICATEUR is None:
                    return self._envoyer(501, {"erreur": "La vérification des modèles n'est pas disponible dans ce mode de lancement."})
                portee = str(donnees.get("portee", "tout"))
                if portee not in ("maj", "nouveaux", "tout"):
                    raise ValueError("Portée inconnue.")
                return self._envoyer(200, _m.VERIFICATEUR(portee))
            if self.path == "/api/propositions-traiter":
                return self._envoyer(200, _m.traiter_proposition(str(donnees.get("cle", "")), bool(donnees.get("appliquer"))))
            if self.path == "/api/taches-effacer":
                ident = str(donnees.get("conversation", ""))
                with _m.VERROU_TOURS:
                    travaille = ident in _m.TOURS_ACTIFS               # un tour en cours réécrit la conversation : on ne la touche pas
                if not travaille:
                    c = _m.conv_lire(ident)
                    c["taches"] = []
                    _m.conv_ecrire(c)
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/arreter":
                return self._envoyer(200, _m.arreter_conversation(str(donnees.get("conversation", ""))))
            if self.path == "/api/approuver":
                _m.repondre_attente(str(donnees.get("id", "")), donnees.get("ok"))
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/reglages":
                return self._envoyer(200, _m.enregistrer_reglages(donnees))
            if self.path == "/api/memoire":
                _m.ecrire_memoire(str(donnees.get("fichier", "")), str(donnees.get("texte", "")))
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/skills":
                return self._envoyer(200, _m.ecrire_skill(str(donnees.get("nom", "")), str(donnees.get("texte", ""))))
            if self.path == "/api/skills-supprimer":
                return self._envoyer(200, _m.supprimer_skill(str(donnees.get("nom", ""))))
            if self.path == "/api/nouvelle":
                return self._envoyer(200, _m.conv_nouvelle())
            if self.path == "/api/supprimer":
                _m.conv_supprimer(str(donnees.get("id", "")))
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/renommer":
                c = _m.conv_renommer(str(donnees.get("id", "")), str(donnees.get("titre", "")))
                return self._envoyer(200, {"ok": True, "titre": c["titre"]})
            if self.path == "/api/titre-ia":
                return self._titre_ia(donnees)
            if self.path == "/api/installer-modele":
                return self._envoyer(200, _m.installer_modele(str(donnees.get("modele", ""))))
            if self.path == "/api/compacter":
                return self._envoyer(200, _m.compacter_conversation(str(donnees.get("conversation", ""))))
            if self.path == "/api/plan":
                _m.rafraichir_plan(force=True)
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/rappeler":
                try:
                    return self._envoyer(200, {"texte": _m.outil_rappeler(str(donnees.get("requete", "")), 6)})
                except _m.ErreurOutil as erreur:
                    raise ValueError(str(erreur))
            if self.path == "/api/oublier-modele":
                return self._envoyer(200, _m.oublier_modele(str(donnees.get("modele", ""))))
            if self.path == "/api/modeles-restaurer":
                return self._envoyer(200, _m.restaurer_modeles())
            if self.path == "/api/supprimer-modele":
                return self._envoyer(200, _m.supprimer_modele(str(donnees.get("modele", ""))))
            if self.path == "/api/demarrer-ollama":
                return self._envoyer(200, {"message": _m.demarrer_ollama()})
            if self.path == "/api/liberer-vram":
                return self._envoyer(200, _m.liberer_vram())
            if self.path == "/api/resumer":
                return self._resumer(donnees)
        except (ValueError, OSError, TypeError, subprocess.SubprocessError) as erreur:
            return self._envoyer(400, {"erreur": str(erreur)})
        return self._envoyer(404, {"erreur": "introuvable"})

    def _appairer(self, donnees):
        if _m.SECURITE.niveau == _sec.LOCAL:
            return self._envoyer(400, {"erreur": "Cet accès est réservé à cette machine : pas de code à saisir."})
        if not _m.LIMITEUR_PIN.autoriser(self.client_address[0]):
            return self._envoyer(429, {"erreur": "Trop d'essais : attends une minute."})
        jeton = _m.APPAREILS.appairer(str(donnees.get("pin", "")), _sec.nom_appareil(donnees.get("nom"), self.headers.get("User-Agent"), self._sur_cette_machine()))
        if not jeton:
            return self._envoyer(403, {"erreur": "Code incorrect ou expiré. Demande-en un nouveau sur l'ordinateur (lutin pin)."})
        return self._envoyer(200, {"ok": True}, en_tetes={"Set-Cookie": _sec.en_tete_set_cookie(jeton, _m.SECURITE.url_publique.startswith("https://"))})

    def _chat(self, donnees):
        texte = str(donnees.get("message", "")).strip()
        if not texte or len(texte) > 60000:
            return self._envoyer(400, {"erreur": "Écris un message (60 000 caractères au maximum)."})
        try:
            images = _images.verifier_liste(donnees.get("images"))
            pieces = _pieces.verifier_liste(donnees.get("pieces"))
        except ValueError as erreur:
            return self._envoyer(400, {"erreur": str(erreur)})
        ident = str(donnees.get("conversation") or "")
        with _m.VERROU_TOURS:                                   # trop de réponses en cours : on refuse avant de créer quoi que ce soit
            if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES and ident not in _m.TOURS_ACTIFS:
                return self._envoyer(429, {"erreur": "Déjà {} réponses en cours : une seule carte graphique, attends la fin de l'une d'elles (ou clique sur Arrêter).".format(len(_m.TOURS_ACTIFS))})
        _fond.interrompre_pour_utilisateur(8)                    # le travail de fond cède la place : son document en cours sera refait plus tard
        conv = _m.conv_lire(ident) if ident else _m.conv_nouvelle()
        depuis = donnees.get("remplacer_depuis")
        if depuis is not None:
            try:
                depuis = int(depuis)
            except (TypeError, ValueError):
                return self._envoyer(400, {"erreur": "Indice de message invalide."})
            if not (0 <= depuis < len(conv["messages"]) and conv["messages"][depuis].get("role") == "user"):
                return self._envoyer(400, {"erreur": "Ce message n'existe plus dans la conversation : recharge-la."})
        stop = threading.Event()
        with _m.VERROU_TOURS:
            if conv["id"] in _m.TOURS_ACTIFS:
                return self._envoyer(409, {"erreur": "Cette conversation est déjà en train de répondre (autre onglet ou téléphone ?). Attends la fin ou clique sur Arrêter."})
            if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
                return self._envoyer(429, {"erreur": "Déjà {} réponses en cours : une seule carte graphique, attends la fin de l'une d'elles (ou clique sur Arrêter).".format(len(_m.TOURS_ACTIFS))})
            try:
                _m.activer_travail(conv, str(donnees.get("travail") or ""))
            except ValueError as erreur:
                return self._envoyer(409, {"erreur": str(erreur)})
            _m.RACINE_TOURS[conv["id"]] = str(_m.RACINE)
            _m.TOURS_ACTIFS[conv["id"]] = stop
        try:
            r = _m.reglages()
            for k in ("modele", "reflexion", "mode"):
                if k in donnees:
                    r[k] = donnees[k]
            if not _modes.valide(r["mode"]):
                return self._envoyer(400, {"erreur": "Mode inconnu."})
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            def emit(evenement):
                # Si la page est fermée (téléphone verrouillé, rechargement), le tour continue et la conversation est enregistrée à la fin.
                try:
                    self.wfile.write((json.dumps(_m.traduire_evenement(evenement), ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except (OSError, ValueError):
                    pass
            emit({"type": "debut", "conversation": conv["id"]})
            _m.tour(conv, texte, emit, r, stop, depuis, identite=self._identite(), images=images, pieces=pieces)
        finally:
            with _m.VERROU_TOURS:
                _m.TOURS_ACTIFS.pop(conv["id"], None)
                _m.RACINE_TOURS.pop(conv["id"], None)

    def _resumer(self, donnees):
        """Génère un document de reprise structuré par le modèle, pour coller dans un autre modèle d'IA."""
        ident = str(donnees.get("conversation") or "")
        if not ident:
            return self._envoyer(400, {"erreur": _t("Pas de conversation.")})
        conv = _m.conv_lire(ident)
        r = _m.reglages()
        # Construire le texte de la conversation (rôles + contenu, outils inclus)
        morceaux = []
        if conv.get("resume"):
            morceaux.append(_t("[RÉSUMÉ ANTÉRIEUR]\n") + conv["resume"])
        for m in conv.get("messages", []):
            role = m.get("role", "?")
            contenu = (m.get("content") or "").strip()
            if not contenu:
                continue
            if role == "tool":
                morceaux.append("[OUTIL " + (m.get("tool_name") or "?") + "]\n" + contenu[:800])
            else:
                morceaux.append(("[UTILISATEUR] " if role == "user" else "[ASSISTANT] ") + contenu[:2000])
        texte_conv = "\n\n".join(morceaux)
        if len(texte_conv) > 40000:
            texte_conv = texte_conv[:40000] + "\n[…tronqué…]"
        consigne = (
            _t("Tu vas produire un document de reprise pour un AUTRE modèle d'IA qui doit continuer le travail.\n"
            "Le document doit contenir, dans cet ordre, en markdown :\n"
            "1. ## Objectif — ce que l'utilisateur voulait faire (1-3 phrases)\n"
            "2. ## Ce qui a été fait — liste des tâches terminées, fichiers modifiés, décisions prises\n"
            "3. ## État actuel — où en est-on, ce qui marche, ce qui est en attente\n"
            "4. ## À faire ensuite — les prochaines étapes concrètes, dans l'ordre\n"
            "5. ## Contraintes et règles — préférences utilisateur, règles du projet, limites connues\n"
            "6. ## Fichiers clés — chemins des fichiers importants et leur rôle\n"
            "7. ## Notes techniques — détails utiles (versions, réglages, bugs connus)\n"
            "Sois précis, concis, sans répétition. Pas de blabla. Le document doit être directement collable comme contexte system/user message.\n"
            "Réponds UNIQUEMENT avec le document markdown, sans préambule.\n\n"
            "CONVERSATION :\n") + texte_conv
        )
        corps = {
            "model": r["modele"],
            "messages": [{"role": "user", "content": consigne}],
            "stream": False,
            "options": _m.options_modele(r, 0.3),          # mêmes options que le chat : un autre ferait recharger le modèle (lent, et risque de manquer de mémoire vidéo)
        }
        try:
            req = urllib.request.Request(_m.OLLAMA + "/api/chat", data=json.dumps(_m.avec_garde(corps)).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as flux:
                reponse = json.loads(flux.read().decode("utf-8"))
            texte = reponse.get("message", {}).get("content", "").strip()
            if not texte:
                return self._envoyer(500, {"erreur": _t("Le modèle n'a pas répondu.")})
            return self._envoyer(200, {"texte": texte, "modele": r["modele"]})
        except (OSError, ValueError) as erreur:
            return self._envoyer(500, {"erreur": str(erreur)})

    def _titre_ia(self, donnees):
        """Propose un titre court (3-6 mots) pour la conversation, sans l'appliquer."""
        ident = str(donnees.get("conversation") or donnees.get("id") or "")
        if not ident:
            return self._envoyer(400, {"erreur": _t("Pas de conversation.")})
        conv = _m.conv_lire(ident)
        r = _m.reglages()
        morceaux = []
        for m in conv.get("messages", [])[:20]:
            contenu = (m.get("content") or "").strip()
            if contenu:
                morceaux.append(("[U] " if m.get("role") == "user" else "[A] ") + contenu[:500])
        texte_conv = "\n".join(morceaux)
        if len(texte_conv) > 6000:
            texte_conv = texte_conv[:6000]
        consigne = (
            _t("Donne un TITRE de 3 à 6 mots (en français) qui résume l'objet principal de cette conversation. "
            "Pas de ponctuation finale, pas de guillemets, pas de préambule. Réponds UNIQUEMENT avec le titre.\n\n"
            "CONVERSATION :\n") + texte_conv
        )
        corps = {
            "model": r["modele"],
            "messages": [{"role": "user", "content": consigne}],
            "stream": False,
            "options": _m.options_modele(r, 0.4),          # mêmes options que le chat (voir _resumer)
        }
        try:
            req = urllib.request.Request(_m.OLLAMA + "/api/chat", data=json.dumps(_m.avec_garde(corps)).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as flux:
                reponse = json.loads(flux.read().decode("utf-8"))
            titre = reponse.get("message", {}).get("content", "").strip().strip('"«»').strip()
            titre = " ".join(titre.split())[:60]
            if not titre:
                return self._envoyer(500, {"erreur": _t("Le modèle n'a pas répondu.")})
            return self._envoyer(200, {"titre": titre})
        except (OSError, ValueError) as erreur:
            return self._envoyer(500, {"erreur": str(erreur)})
