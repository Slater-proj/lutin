"""Le serveur HTTP de Lutin : le gestionnaire de requêtes (pages, API JSON, flux de la conversation). L'état et les fonctions métier restent dans moteur ; ce module les atteint par « _m.NOM » (lu à chaque appel)."""
import gzip
import html
from http.server import BaseHTTPRequestHandler
from . import bench as _bench
from . import engine_bench as _bench_moteurs
from . import engine_metrics as _mesures
from . import model_compat as _compat
from . import power as _alimentation
from . import machines as _machines
from . import memory_estimate as _estimation
from . import loaded_resources as _ressources
from . import engine_catalog as _catalogue_moteurs
from . import llamacpp_engine as _llamacpp
from . import engines as _moteurs
from . import web_search as _recherche
from . import outbound as _sorties
from . import observatory as _observatoire
from . import web as _web
from . import engine_updates as _moteurs_maj
from . import mcp as _mcp
from . import mcp_catalog as _mcp_catalogue
from . import external_programs as _outils_externes
from . import calibration as _calibrage
from . import access as _acces
from . import api_v1 as _api_v1
from . import model_fit as _adequation
from . import exllamav3_catalog as _exl_cat
from . import lmstudio_catalog as _lms_cat
from . import github as _github
from . import third_party_skills as _skills
from . import open_file as _ouverture
from . import workspaces as _travaux
from . import performance_advice as _conseil
from . import low_end_mode as _conseil_machine
from . import model_variants as _variantes
from . import diagnostic as _diagnostic
from . import locations as _emplacements
from . import model_discovery as _decouverte
from . import storage as _donnees
from . import offline as _hl
from . import modes as _modes
from . import attachments as _pieces
from . import images as _images
from . import addons as _addons
from . import embeddings as _embeddings
from . import produced_files as _fichiers
from . import hardware as _machine
from . import mission as _mission
from . import background_jobs as _fond
from . import notifications as _notif
from . import scheduled_tasks as _plan
from . import recall as _rappel
from . import progress_sheet as _suivi
from . import i18n as _i18n
from . import claude_project as _pc
from . import backup as _sauv
from . import security as _sec
from .i18n import t as _t
from datetime import datetime
import io
import json
import os
import sys
import time
from pathlib import Path
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from . import core as _m


DELAI_ECRITURE_FLUX = 20      # secondes : une page qui ne lit plus (onglet gelé) ne doit pas figer la réponse
TYPES_COMPRESSIBLES = ("text/html", "application/json", "text/javascript", "application/javascript", "text/css", "image/svg+xml")          # jamais les images ni les archives (déjà compressées)
BATTEMENT_FLUX = 15          # secondes entre deux lignes vides envoyées pour garder le flux ouvert derrière un reverse proxy


ROUTES_MODELES_GERES = {          # les trois serveurs que Lutin gère ont les mêmes routes : (serveur, ce qu'elle rend)
    "/api/{}-{}".format(serveur, route): (serveur, nom) for serveur in ("exllamav3", "lmstudio", "colibri")
    for route, nom in (("modeles", "modeles"), ("catalogue", "catalogue"), ("quantifications", "quantifications"))}


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
        if code == 403 and isinstance(corps, dict) and "cette machine" in str(corps.get("erreur", "")) and _acces.en_docker():
            corps = dict(corps, erreur=str(corps["erreur"]) + _t(" Dans Docker : ajoute LUTIN_ADMIN_TOUS=1 aux variables du conteneur (ou, derrière un proxy, ton identifiant dans LUTIN_ADMINS), puis redémarre-le."))
        elif code == 403 and isinstance(corps, dict) and "cette machine" in str(corps.get("erreur", "")):
            corps = dict(corps, erreur=str(corps["erreur"]) + _t(" Pour le faire depuis un autre appareil : Accès > Administration à distance (à activer depuis cette machine)."))
        if isinstance(corps, dict) and _i18n.langue() != "fr":
            corps = _m.traduire_json(corps)
        donnees = corps if isinstance(corps, (bytes, bytearray)) else (corps if isinstance(corps, str) else json.dumps(corps, ensure_ascii=False)).encode("utf-8")
        compressible = len(donnees) > 1400 and type_.split(";")[0].strip() in TYPES_COMPRESSIBLES and "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        if compressible:          # la page (370 Ko) et l'état se compressent à environ le quart : sensible sur un téléphone ou le Wi-Fi
            donnees = gzip.compress(bytes(donnees), 5, mtime=0)
        self.send_response(code)
        self.send_header("Content-Type", type_)
        if compressible:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(donnees)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (en_tetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(donnees)

    # ---- sécurité (voir lutin.security) ----
    _via_relais = ""          # nom de la machine appairée dont cette requête est relayée (droit « piloter »), sinon ""

    def _local(self):
        """La requête vient de cette machine : la boucle locale, ou l'adresse de la machine sur le réseau local (un navigateur d'ici qui ouvre http://192.168.x.y:8777 arrive avec cette adresse-là).
        Une autre machine ne peut pas se faire passer pour elle : la connexion TCP n'aboutirait pas."""
        ip = self.client_address[0]
        return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1") or bool(_m.IP_LAN and ip == _m.IP_LAN)

    def _jeton_valide(self):
        if self._via_relais:
            return True                                      # déjà contrôlé par le jeton de nœud (voir _relais)
        donne = self.headers.get("X-Token") or ""
        return any(_sec.egal(donne, attendu) for attendu in (_m.JETON, _m.JETON_CONSOLE))

    def _authentifie(self):
        if self._via_relais:
            return True
        if self._local() and _sec.egal(self.headers.get("X-Token") or "", _m.JETON_CONSOLE):
            return True                                      # la console de cette machine (fichier réservé à l'utilisateur)
        return _sec.acces(_m.SECURITE, _m.APPAREILS, self.client_address[0], self.headers)[0]

    def _identite(self):
        """Qui fait cette requête, pour le journal : « console », « local », le nom donné par le proxy, ou « appareil »."""
        if self._via_relais:
            return "machine : " + self._via_relais
        if self._local() and _sec.egal(self.headers.get("X-Token") or "", _m.JETON_CONSOLE):
            return "console"
        return _sec.acces(_m.SECURITE, _m.APPAREILS, self.client_address[0], self.headers)[1]

    def _sur_cette_machine(self):
        """Le navigateur est sur cette machine : connexion de boucle locale, nom d'hôte de boucle locale, et aucun en-tête laissant croire qu'un relais (proxy, tunnel) a transmis une requête venue d'ailleurs."""
        relais = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "Via", "X-Real-IP")
        return self._local() and not any(self.headers.get(h) for h in relais) and (_sec._est_boucle(_sec._sans_port(self.headers.get("Host") or "")) or bool(_m.IP_LAN and _sec._sans_port(self.headers.get("Host") or "") == _m.IP_LAN))

    def _vue_moteur(self, mo, courant):
        """Un moteur pour la page : description, forces et faiblesses, état, ce qui est possible (ou pourquoi non), tâche en cours, réglages d'adresse sans la clé."""
        v = mo.vue(mo.id == courant)
        modeles = mo.modeles()
        statut = mo.statut()
        return dict(v, statut=statut, actif=bool(modeles["actif"]), nb_modeles=len(modeles["installes"]), actions=mo.actions(), tache=_moteurs.tache(mo.id), telechargeable=mo.telechargeable(), maj=_moteurs_maj.etat().get(mo.id),
                    reglages=_llamacpp.vue_reglages(mo.id) if (mo.adresse_modifiable or hasattr(mo, "info_dossier")) else {})

    @staticmethod
    def _prereglages():
        """Les serveurs compatibles OpenAI du catalogue signé (adresse habituelle, forces, faiblesses), pour les proposer d'un clic. Un catalogue illisible n'empêche jamais la page."""
        try:
            systeme, docker = _llamacpp._systeme(), bool(_moteurs.CONTEXTE["en_docker"]())
            try:
                profil = _moteurs.CONTEXTE["profil"]()
                fabricants = sorted({g.fabricant for g in (getattr(profil, "gpus", None) or [])})
            except Exception:  # noqa: BLE001  (profil illisible : aucun serveur n'est écarté à cause du matériel... sauf ceux qui exigent une carte)
                fabricants = []
            sortie = []
            for m in _catalogue_moteurs.en_cours()["moteurs"]:
                if m.get("type", "externe") != "externe":
                    continue
                v = dict(_catalogue_moteurs.vue(m))
                v["compatible"], v["raison_incompatible"] = _catalogue_moteurs.compatibilite(v, systeme, docker, fabricants)          # filtré selon la machine où Lutin tourne (système, Docker, carte graphique)
                sortie.append(v)
            return sortie
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _diagnostic_moteur(mo, o, r):
        """Pour un moteur autre qu'Ollama : ce qui empêche de discuter (moteur absent ou muet, aucun modèle, modèle choisi absent)."""
        ouvrir = {"type": "onglet", "nom": "reglages"}
        if not o["actif"]:
            return [{"niveau": "erreur", "texte": _t("Le moteur « {} » n'est pas prêt : installe-le ou vérifie son adresse.").format(mo.nom), "action": ouvrir}]
        if not o["installes"]:
            return [{"niveau": "attention", "texte": _t("Aucun modèle sur le moteur « {} » : télécharges-en un dans l'onglet Modèles.").format(mo.nom), "action": {"type": "onglet", "nom": "modeles"}}]
        if r["modele"] not in o["installes"]:
            return [{"niveau": "attention", "texte": _t("Le modèle « {} » n'existe pas sur le moteur « {} » : choisis-en un autre.").format(r["modele"], mo.nom), "action": {"type": "onglet", "nom": "modeles"}}]
        return []

    @staticmethod
    def _memoire(r, o):
        """Le modèle de conversation est-il chargé, et combien de mémoire prend-il (carte graphique / mémoire vive) ? Pour la barre d'état. None si Ollama est arrêté ou le modèle déchargé."""
        if not o["actif"]:
            return None
        ps = _m.ps_modele(r["modele"])
        return {"modele": r["modele"], "taille": ps["taille"], "vram": ps["vram"]} if ps else None

    @staticmethod
    def _variantes_jugees(modele):
        """Les variantes de précision de `modele` avec, pour chacune, ce que cette machine en dit (tient ou pas) et si elle est déjà installée."""
        lues = _variantes.lister(modele)
        profil = _adequation.profil_pret()
        base = next((m for m in _m._CATALOGUE["modeles"] if m["id"] == modele), {})
        installes = set(_m.etat_moteur()["installes"])
        sortie = []
        for v in lues["variantes"]:
            jugement = _adequation.evaluer(dict(base, go=v["go"]), profil) if profil is not None else {"niveau": "bien", "texte": ""}
            sortie.append(dict(v, installe=v["id"] in installes, niveau=jugement["niveau"], jugement=jugement["texte"], explication=_variantes.decrire(v["precision"])))
        return {"modele": modele, "defaut": lues["defaut"], "variantes": sortie}

    @staticmethod
    def _compat(o):
        """Pour chaque modèle du catalogue : compatible avec le moteur choisi ? (format, quantification, mémoire estimée, raisons). La page ne propose que les compatibles."""
        try:
            return _compat.pour_la_liste(_m._CATALOGUE["modeles"], _m.moteur_actuel(), o["installes"])
        except Exception:  # noqa: BLE001  (jamais une page cassée : sans cette liste, rien n'est masqué)
            return {}

    @staticmethod
    def _estimation(modele, ctx, profil):
        """L'estimation AVANT chargement pour un modèle du catalogue (mémoire prise, où, saturation, conseils), ou None si le modèle n'est pas au catalogue."""
        m = next((x for x in _m._CATALOGUE["modeles"] if x["id"] == modele), None)
        if m is None:
            return None
        e = _estimation.estimer(m, int(ctx), profil)
        e["modele"] = modele
        e["preset_experts"] = _estimation.preset_experts(m, profil, int(ctx))
        return e

    @staticmethod
    def _avec_estimation(diagnostic, r, profil):
        """Le modèle choisi ne tient pas (ou à peine) : le dire dans la bannière, AVANT qu'on le charge."""
        try:
            e = Gestionnaire._estimation(r["modele"], r["num_ctx"], profil)
            if e and e["niveau"] in ("trop_gros", "sature") and not any(p.get("code") == "modele_trop_gros" for p in diagnostic):
                diagnostic = list(diagnostic) + [{"code": "estimation", "niveau": "attention" if e["niveau"] == "sature" else "erreur", "texte": e["texte"] + (" " + e["conseils"][0] if e["conseils"] else ""), "action": {"type": "onglet", "nom": "modeles"}}]
        except Exception:  # noqa: BLE001  (un plus : jamais une page cassée)
            pass
        return diagnostic

    @staticmethod
    def _premier_lancement(o, r, profil):
        """Aucun moteur prêt ? La page désactive l'onglet Modèles avec la raison et propose le moteur conseillé (installer / choisir autre / plus tard)."""
        try:
            mo = _m.moteur_actuel(r)
            if o["actif"]:
                return _diagnostic.premier_lancement(mo.nom, True, "")
            reco = None          # pas de mo.statut() ici : il sonde le moteur (2 s) et /api/etat doit rester immédiat
            try:
                reco = _bench_moteurs.recommander(profil, banc=None, docker=_moteurs.CONTEXTE["en_docker"](), modele_installe=False)
            except Exception:  # noqa: BLE001  (la recommandation est un plus)
                reco = None
            from . import docker_engines as _md
            dossier = _md.dossier_moteurs()          # Docker : où le moteur sera installé, et si c'est un volume dédié (/engines) ou le volume des données
            detail_dossier = _md.detail_dossier_moteurs() if dossier else {}
            emplacement = {"dossier": str(dossier), "dedie": detail_dossier.get("source") in ("env", "reglage", "montage"), "probleme": detail_dossier.get("probleme", ""), "montage": _md.MONTAGE} if dossier else None
            autres = []          # les autres moteurs déjà sur la machine (simple regard sur les fichiers, aucune sonde réseau)
            for autre in _moteurs.MOTEURS.values():
                try:
                    if autre.id == mo.id:
                        continue
                    if (autre.id == "ollama" and _m.chemin_ollama()) or (autre.id == "llamacpp" and autre.serveur_pret() is not None):
                        autres.append({"moteur": autre.id, "nom": autre.nom})
                except Exception:  # noqa: BLE001
                    continue
            if mo.id == "ollama":
                detail = _t("Installé, mais arrêté.") if _m.chemin_ollama() else _t("Pas installé.")
            elif mo.id == "llamacpp":
                detail = _t("Installé, il démarre à la demande.") if mo.serveur_pret() is not None else _t("Pas installé.")
            else:
                detail = ""
            gere = None          # Colibri, LM Studio ou ExLlamaV3 choisi : simple regard sur les fichiers (aucune sonde réseau)
            if mo.id == "openai":
                for choisi, nom, trouve in (("colibri_choisi", "Colibri", getattr(mo, "_colibri", None)), ("lmstudio_choisi", "LM Studio", getattr(mo, "_lms", None)), ("exllamav3_choisi", "ExLlamaV3", getattr(mo, "_exl", None))):
                    if trouve and getattr(mo, choisi, lambda: False)():
                        gere = {"nom": nom, "installe": trouve() is not None}
                        if choisi == "colibri_choisi" and gere["installe"]:
                            try:
                                gere["sans_modele"] = not mo.modele_colibri()          # Colibri ne démarre qu'avec un modèle qu'il a préparé : sans lui, « Démarrer » ne peut rien faire
                            except Exception:  # noqa: BLE001
                                pass
            return _diagnostic.premier_lancement(mo.nom, False, detail, {k: reco[k] for k in ("moteur", "nom", "raison")} if reco else None, emplacement, autres, mo.id, gere)
        except Exception:  # noqa: BLE001  (jamais une page cassée pour un constat de plus)
            return {"pret": True, "raison": "", "recommande": None}

    REFLEXION = {}          # (moteur, machine, modèle) -> (instant, résultat) : /api/etat est demandé très souvent, le moteur ne doit pas être interrogé à chaque fois

    @staticmethod
    def _reflexion_possible(r, actif=True):
        """Le modèle choisi a-t-il un mode réflexion ? True / False, ou None quand le moteur ne le dit pas ou ne répond pas (la case reste alors libre). La page grise et décoche la case quand c'est False."""
        if not actif:
            return None
        cle = (r.get("moteur"), r.get("machine"), r["modele"])
        gardee = Gestionnaire.REFLEXION.get(cle)
        if gardee and time.monotonic() - gardee[0] < 30:
            return gardee[1]
        try:
            caps = _m.capacites(r["modele"])
        except Exception:  # noqa: BLE001  (un confort : jamais une page cassée)
            caps = None
        valeur = None if caps is None else ("thinking" in caps)
        Gestionnaire.REFLEXION[cle] = (time.monotonic(), valeur)
        return valeur

    @staticmethod
    def _diagnostic(o, r, profil, modeles):
        """Ce qui empêche Lutin de répondre (ou le gêne), pour la bannière du haut de la page."""
        mo = _m.moteur_actuel(r)
        if _machines.modele_distant(r, o["installes"]):          # le modèle choisi est celui d'une autre machine : il n'a pas à exister ici ni à tenir sur cette carte
            if mo.id != "ollama":
                return []
            r = dict(r, modele="")
        if mo.id != "ollama":
            return Gestionnaire._diagnostic_moteur(mo, o, r)
        jauge = _emplacements.jauge_modeles() or {}
        libre = jauge.get("libre")
        try:
            return _diagnostic.diagnostiquer(o["actif"], bool(_m.chemin_ollama()), [n for n in o["installes"] if not _embeddings.est_modele_de_recherche(n)], r, profil, _m._CATALOGUE, _adequation.pour_la_liste(modeles, profil, _m._CATALOGUE["modeles"]),
                                             libre / 1e9 if libre else None, conseils=_conseil_machine.conseils(profil, r), modeles_ailleurs=_emplacements.modeles_ailleurs(o["installes"]) if o["actif"] else None)
        except (KeyError, TypeError, ValueError, AttributeError):
            return []

    @staticmethod
    def _admin_tous():
        """Le propriétaire a ouvert la configuration à toute personne déjà admise par le niveau d'accès : Docker (LUTIN_ADMIN_TOUS=1 dans le docker-compose, car le navigateur n'y est jamais « sur la machine »)
        ou, partout, le réglage Accès > Administration à distance (qui ne se change que depuis la machine elle-même)."""
        if _acces.en_docker() and os.environ.get("LUTIN_ADMIN_TOUS", "").strip().lower() in ("1", "true", "oui", "yes", "on"):
            return True
        try:
            return bool(_m.config_lue().get("admin_a_distance"))
        except (OSError, ValueError):
            return False

    def _configurateur(self):
        """Peut-on configurer depuis cette page ? Oui depuis la machine elle-même, ou depuis n'importe quel appareil admis si le propriétaire a ouvert l'administration à distance."""
        if self._via_relais:
            return False                                     # une machine qui pilote une conversation ne configure jamais celle-ci
        if self._admin_tous():
            return self._authentifie()
        return self._configurateur_strict()

    def _configurateur_strict(self):
        """Peut-on changer ce qui ouvre ou modifie la machine (dossiers de travail, niveau d'accès, restauration) ? Seulement depuis cette machine : au niveau « machine seulement », avec le jeton de la console,
        ou — au niveau « réseau » — depuis le navigateur de cette machine (jamais depuis un appareil appairé). Derrière un proxy, la commande lutin seulement : le proxy est sur la machine, il ne prouve rien.
        C'est la règle d'origine, sans l'ouverture à distance (voir _configurateur) : elle seule peut activer ou retirer l'administration à distance."""
        if self._via_relais:
            return False
        if _m.SECURITE.niveau == _sec.LOCAL:
            return True
        if self._local() and _sec.egal(self.headers.get("X-Token") or "", _m.JETON_CONSOLE):
            return True
        if _sec.est_admin_proxy(_m.SECURITE, self.client_address[0], self.headers):
            return True                                                    # niveau proxy : un administrateur déclaré (LUTIN_ADMINS) identifié par le proxy de confiance (Authelia…)
        return _m.SECURITE.niveau == _sec.RESEAU and self._sur_cette_machine()

    def _controle(self, ecriture):
        """Nom d'hôte (contre le « DNS rebinding ») et origine (contre les requêtes venues d'autres sites). Répond lui-même en cas de refus."""
        if not _sec.hote_autorise(_m.SECURITE, self.headers.get("Host"), _m.IP_LAN):
            code, message = "host_not_allowed", "nom d'hôte non autorisé"
        elif ecriture and not _sec.origine_autorisee(_m.SECURITE, self.headers.get("Origin"), self.headers.get("Host"), _m.IP_LAN):
            code, message = "origin_not_allowed", "origine non autorisée"
        else:
            return True
        if self.path.split("?")[0].startswith("/api/v1/"):      # l'API versionnée refuse dans SA forme (un code, un message) et lit le corps avant de répondre
            _api_v1.refuse(self, 403, code, message)
        else:
            self._envoyer(403, {"erreur": message})
        return False

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
        if chemin.startswith("/api/v1/"):                      # l'API versionnée, en anglais (lutin.api_v1) : droits déclarés dans sa table, erreurs avec un code
            return _api_v1.dispatch(self, "GET")
        if chemin.startswith("/api/noeud/relais/"):            # une machine appairée mène une conversation ICI (droit « piloter »)
            return self._relais("GET")
        if chemin.startswith("/h/"):                           # cette page affiche une conversation menée sur une autre machine
            return self._vers_hote("GET")
        if chemin == "/api/noeud/etat":                        # une autre machine demande si ce Lutin peut faire tourner un modèle : jeton de nœud, rien d'autre n'est ouvert
            return self._noeud_etat()
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
        if chemin.startswith("/piece/"):                       # télécharger de nouveau un fichier envoyé par l'utilisateur, sous son vrai nom
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                octets, mime, nom = _fichiers.piece_lire(chemin[len("/piece/"):], (q.get("nom") or [""])[0])
            except ValueError as e:
                return self._envoyer(404, {"erreur": str(e)})
            return self._envoyer(200, octets, mime, {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nom), "Content-Security-Policy": "default-src 'none'; sandbox"})
        if chemin == "/api/ouvrir-chemin" or chemin.startswith("/ouvrir/"):          # un chemin cité dans une réponse devient un lien : le fichier du DOSSIER DE TRAVAIL s'ouvre dans le navigateur (jamais lancé)
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                if chemin == "/api/ouvrir-chemin":
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    trouve = _ouverture.resoudre((q.get("p") or [""])[0], _m.RACINE)
                    if trouve is None:
                        return self._envoyer(404, "<!doctype html><meta charset=utf-8><title>Lutin</title><body style='font-family:sans-serif;margin:3em'><h3>" + html.escape(_t("Fichier introuvable dans le dossier de travail.")) + "</h3><p>"
                                             + html.escape(_t("Lutin ne retrouve que les fichiers du dossier de travail actif ({}). Si le fichier est ailleurs, ajoute son dossier comme dossier de travail (Réglages > Dossiers).").format(_m.RACINE)) + "</p>", "text/html; charset=utf-8")
                    return self._envoyer(302, b"", "text/plain", {"Location": _ouverture.adresse(trouve, _m.RACINE)})
                octets, mime, entetes = _ouverture.lire(chemin[len("/ouvrir/"):], _m.RACINE)
            except ValueError as e:
                return self._envoyer(404, "<!doctype html><meta charset=utf-8><title>Lutin</title><body style='font-family:sans-serif;margin:3em'><h3>" + html.escape(str(e)) + "</h3>", "text/html; charset=utf-8")
            return self._envoyer(200, octets, mime, entetes)
        if chemin.startswith("/fichier/"):                     # télécharger un fichier produit pendant une conversation (cookie de session, comme /image/)
            if not self._authentifie():
                return self._envoyer(401, {"erreur": "authentification requise"})
            try:
                _, ident, fichier_id = chemin.split("/", 3)[1:]
                octets, mime, nom = _fichiers.lire(ident, fichier_id)
            except ValueError as e:
                return self._envoyer(404, {"erreur": str(e)})
            return self._envoyer(200, octets, mime, {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nom), "Content-Security-Policy": "default-src 'none'; sandbox"})
        if chemin in ("/", "/index.html"):
            return self._envoyer(200, _m.page_web(), "text/html; charset=utf-8")
        if chemin == "/api/etat":
            o = _m.etat_moteur()
            r = _m.reglages()
            modeles = _m.modeles_connus(o["installes"], o.get("tailles"))
            profil = _adequation.profil_pret()
            return self._envoyer(200, {"compat": self._compat(o), "adequation": _adequation.pour_la_liste(modeles, profil, _m._CATALOGUE["modeles"]), "machine": profil.resume() if profil else "", "budget_go": profil.budget_go() if profil else 0,
                                       "familles": {k: _t(v) for k, v in (_m._CATALOGUE.get("familles") or {}).items()}, "disque_modeles": _emplacements.jauge_modeles(),
                                       "version": _m.VERSION, "partages": o.get("partages", []), "ollama": o["actif"], "ollama_installe": bool(_m.chemin_ollama()) or _m.moteur_actuel().id != "ollama", "moteur_nom": _mesures.nom_affiche(_m.moteur_actuel()), "installes": o["installes"], "modeles": modeles, "modeles_masques": len(_m.lire_registre_modeles()["masques"]), "actives": list(_m.TOURS_ACTIFS),
                                       "pulls": _m.PULLS, "reglages": r, "conversations": _m.conv_liste(), "racine": str(_m.RACINE), "donnees": str(_m.DONNEES),
                                       "colibri_choisi": bool(getattr(_m.moteur_actuel(r), "colibri_choisi", lambda: False)()), "lmstudio_choisi": bool(getattr(_m.moteur_actuel(r), "lmstudio_choisi", lambda: False)()), "exllamav3_choisi": bool(getattr(_m.moteur_actuel(r), "exllamav3_choisi", lambda: False)()), "outil": bool(self._outil_vivant()), "hors_ligne": _hl.actif(), "moteur": _m.moteur_actuel().id, "niveau": _m.SECURITE.niveau, "docker": _acces.en_docker(), "ouverture_possible": _fichiers.ouverture_possible(), "missions": _mission.par_conversation(), "langue": _i18n.langue(), "langue_reglage": _i18n.langue_configuree(), "cpus": _machine.cpus_disponibles() or 1, "diagnostic": self._avec_estimation(self._diagnostic(o, r, profil, modeles), r, profil), "prudent": _estimation.mode_prudent(profil), "premier_lancement": self._premier_lancement(o, r, profil), "redemarrage": {"necessaire": _acces.securite_enregistree() != _m.SECURITE, "possible": _acces.peut_redemarrer()}, "nouvelle_version": _m.nouvelle_version_lutin(), "travaux": _m.travaux_etat(), "configurateur": self._configurateur(), "addons_alertes": _addons.alertes(), "embeddings": _embeddings.etat(),
                                       "reflexion_possible": self._reflexion_possible(r, o["actif"]), "cluster_actif": _machines.cluster_actif(r.get("cluster")), "demandes_machines": len(_machines.noeud().get("demandes", [])), "modeles_distants": _machines.modeles_distants() if _machines.cluster_actif(r.get("cluster")) else [], "conversations_distantes": _machines.conversations_distantes() if _machines.cluster_actif(r.get("cluster")) else [], "machines_hors_ligne": _machines.hors_ligne() if _machines.cluster_actif(r.get("cluster")) else [], "taches_fond": _m.taches_en_cours(), "taches_moteur": [dict(v, nom=_moteurs.MOTEURS[k].nom) for k, v in _moteurs.toutes_les_taches().items() if v.get("statut") == "en cours" and k in _moteurs.MOTEURS], "fins_moteur": _moteurs.fins_recentes(), "memoire": self._memoire(r, o), "calibrage": _calibrage.etat(), "bench": {"en_cours": _m.BENCH["en_cours"], "etape": _m.BENCH["etape"], "erreur": _m.BENCH["erreur"], "file": list(_m.BENCH.get("file") or []), "mesures": _bench.lire(_m.chemin_bench())}, "attentes": [{"id": a.id, "titre": a.titre, "detail": a.detail, "diff": a.diff, "conv": a.conv} for a in _m.Attente.EN_COURS.values()],
                                       "en_attente": sorted({a.conv for a in _m.Attente.EN_COURS.values() if a.conv} | set(_m.CHOIX_MEMOIRE))})
        if chemin == "/api/conseil":
            r = _m.reglages()
            vitesse = ((_bench.lire(_m.chemin_bench()).get(r["modele"]) or {}).get("resultats") or {}).get("vitesse")
            if not vitesse or not vitesse.get("tok_s"):
                return self._envoyer(200, {"mesure": None, "conseil": []})
            from .hardware import detecter
            return self._envoyer(200, {"mesure": vitesse, "conseil": _conseil.analyser(vitesse, detecter(), r, _m._CATALOGUE, _m.etat_moteur()["installes"], _m.ps_modele(r["modele"]))})
        if chemin == "/api/notifications":
            return self._envoyer(200, {"canaux": _notif.lister(), "types": _notif.types()})
        if chemin == "/api/planifie":
            return self._envoyer(200, _plan.etat())
        if chemin == "/api/github":                              # le compte GitHub (facultatif) : configuré ou non, jamais le jeton
            return self._envoyer(200, dict(_github.vue(), modifiable=self._configurateur()))
        if chemin.startswith("/api/skills-tiers"):               # skills tiers : sources, recherche, fiche, installés
            return self._skills_tiers_lire(chemin)
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
            return self._envoyer(200, _acces.etat(self._configurateur(), self._configurateur_strict(), self._admin_tous()))
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
        if chemin == "/api/variantes":                           # les précisions (q4, q8, fp16…) d'un modèle de la bibliothèque, jugées pour CETTE machine
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                return self._envoyer(200, self._variantes_jugees((q.get("modele") or [""])[0]))
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
            except OSError as e:
                return self._envoyer(503, {"erreur": str(e)})
        if chemin == "/api/moteurs":                             # les moteurs de modèles : leur état, ce qui est possible avec chacun, et celui qui est choisi
            courant = _m.moteur_actuel().id
            _moteurs_maj.en_arriere_plan(bool(_m.reglages().get("verifier_maj", True)) and not _hl.actif())          # au plus un contrôle par 24 h, en arrière-plan : la carte du moteur l'affichera au prochain rafraîchissement
            return self._envoyer(200, {"courant": courant, "modifiable": self._configurateur(), "moteurs": [self._vue_moteur(mo, courant) for mo in _moteurs.liste()], "prereglages": self._prereglages(), "dossier_moteurs": _llamacpp.vue_dossier_moteurs()})
        if chemin in ("/api/moteur-recherche", "/api/moteur-fichiers"):          # chercher un modèle (Hugging Face pour llama.cpp), puis voir les fichiers d'un dépôt
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            mo = _moteurs.par_id((q.get("moteur") or [""])[0])
            try:
                if chemin == "/api/moteur-recherche":
                    return self._envoyer(200, {"resultats": mo.chercher_modeles((q.get("q") or [""])[0])})
                return self._envoyer(200, {"fichiers": mo.fichiers_du_depot((q.get("repo") or [""])[0])})
            except AttributeError:
                return self._envoyer(400, {"erreur": _t("Ce moteur n'a pas de bibliothèque de modèles à parcourir.")})
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/outils":                              # uv et Node.js : ce qui est installé (par Lutin ou sur la machine)
            return self._envoyer(200, {"outils": _outils_externes.etat(), "modifiable": self._configurateur()})
        if chemin == "/api/mcp-catalogue":                       # les connecteurs du catalogue (sans rien lancer)
            return self._envoyer(200, {"serveurs": _mcp_catalogue.liste(), "modifiable": self._configurateur()})
        if chemin == "/api/mcp":                                 # les connecteurs MCP (sans leurs secrets)
            return self._envoyer(200, {"connecteurs": _mcp.vue(), "modifiable": self._configurateur(), "limite": _mcp.limite_outils()})
        if chemin == "/api/decouvrir":                           # la bibliothèque d'Ollama (nouveautés, populaires, recherche)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                r = _decouverte.chercher((q.get("q") or [""])[0], (q.get("o") or ["newest"])[0], (q.get("p") or ["1"])[0], categorie=(q.get("c") or [""])[0], leger=(q.get("leger") or ["0"])[0] == "1")
                profil = _adequation.profil_pret()
                juger = (lambda go: _adequation.evaluer({"go": go}, profil)) if profil is not None else (lambda go: {"niveau": "bien", "texte": ""})
                installes = set(_m.etat_moteur()["installes"])
                modeles = _decouverte.evaluer_tailles(r["modeles"], juger)
                for m in modeles:
                    m["installes"] = sorted(t for t in m["tailles"] if m["nom"] + ":" + t in installes) + ([""] if m["nom"] in installes or m["nom"] + ":latest" in installes else [])
                return self._envoyer(200, dict(r, modeles=modeles))
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
        if chemin == "/api/addon-etat":                          # le panneau d'un addon actif (ex. Telegram : code d'appairage, brouillons) : seulement depuis cette machine
            if not self._configurateur():
                return self._envoyer(403, {"erreur": _t("Les extensions se gèrent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                return self._envoyer(200, _addons.etat_vivant((q.get("id") or [""])[0]))
            except _addons.ErreurAddon as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/addon-flux":                          # le flux en vigueur et celui qui est livré (éditeur de flux)
            if not self._configurateur():
                return self._envoyer(403, {"erreur": _t("Les extensions se gèrent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            ident = (q.get("id") or [""])[0]
            try:
                _addons.manifeste(ident)
                return self._envoyer(200, {"flux": _addons.flux(ident), "livre": _addons.flux_livre(ident), "modifie": _addons.flux_modifie(ident)})
            except _addons.ErreurAddon as e:
                return self._envoyer(400, {"erreur": str(e)})
        if chemin == "/api/missions":                            # les missions longues : état et avancement
            return self._envoyer(200, _mission.etat())
        if chemin == "/api/fichiers-crees":                      # tout ce que Lutin a créé (documents, images, vidéos, sons) : de quoi faire le ménage
            return self._envoyer(200, _fichiers.lister())
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
        if chemin == "/api/dossier-modeles-chercher":            # retrouver des modèles déjà téléchargés (autre disque, ancien dossier)
            if not self._configurateur():
                return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
            return self._envoyer(200, {"dossiers": _emplacements.chercher_dossiers_modeles(connus=[_emplacements.dossier_vu(), os.environ.get("OLLAMA_MODELS", ""), _emplacements.lire_config_modeles()]), "actuel": str(_emplacements.dossier_modeles())})
        if chemin == "/api/dossier-modeles-etat":
            return self._envoyer(200, _emplacements.etat_copie())
        if chemin == "/api/emplacements":                        # tous les dossiers que Lutin utilise, leur taille et la place libre
            from . import locations
            return self._envoyer(200, dict(locations.lister(), modifiable=self._configurateur()))
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
        if chemin == "/api/bench-moteurs":                        # comparaison des moteurs : dernier résultat, recommandation et sa raison, avancement
            return self._envoyer(200, _bench_moteurs.vue(_m.DONNEES, _m.reglages()["modele"], _moteurs.CONTEXTE["profil"](), _moteurs.CONTEXTE["en_docker"]()))
        if chemin == "/api/estimation":                          # estimer AVANT de charger : mémoire prise, où, saturation, conseils, préréglage des modèles à experts
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            modele = (q.get("modele") or [""])[0] or _m.reglages()["modele"]
            try:
                ctx = int((q.get("ctx") or [_m.reglages()["num_ctx"]])[0])
            except ValueError:
                return self._envoyer(400, {"erreur": _t("Fenêtre de conversation invalide.")})
            e = self._estimation(modele, max(512, min(ctx, 1048576)), _adequation.profil_pret())
            return self._envoyer(200 if e else 404, e or {"erreur": _t("Ce modèle n'est pas au catalogue : pas d'estimation possible.")})
        if chemin == "/api/observatoire":                         # Santé : ce que les modèles et les outils ont fait (noms, durées, compteurs ; jamais le texte des messages)
            evenements = _observatoire.lire(400)
            return self._envoyer(200, {"resume": _observatoire.resume(evenements), "recents": [e for e in evenements if e["type"] != "tour"][:25], "modifiable": self._configurateur()})
        if chemin == "/api/bench-historique":                     # Santé : l'évolution des mesures de chaque modèle et les régressions
            historique = _bench.lire_historique(_m.chemin_bench())
            return self._envoyer(200, {"regressions": _bench.regressions(_m.chemin_bench()), "modeles": [{"modele": m, "mesures": v[-6:]} for m, v in historique.items() if len(v) >= 1]})
        if chemin == "/api/sorties":                              # Santé : ce qui est sorti de la machine (recherches envoyées à un service extérieur)
            return self._envoyer(200, {"entrees": _sorties.lire(60), "modifiable": self._configurateur()})
        if chemin == "/api/web-recherche":                        # Réglages > Recherche web : ce qui est réglé (jamais la clé) et l'ordre des moteurs
            return self._envoyer(200, dict(_recherche.vue(), moteurs=_m.etat_moteurs_recherche(), modifiable=self._configurateur()))
        if chemin == "/api/mesures-moteurs":                      # Réglages > Moteur : ce que chaque moteur a donné ici (classement des mesures) et ceux qu'on peut mesurer maintenant
            return self._envoyer(200, _mesures.vue(_m.DONNEES, dict(_moteurs.MOTEURS), _m.reglages()))
        if chemin.split("?")[0] in ROUTES_MODELES_GERES:          # onglet Modèles d'un serveur géré par Lutin : ce qui est téléchargé, ce qu'on peut télécharger, jugé pour cette machine
            return self._modeles_serveur_gere(chemin)
        if chemin == "/api/machines":                             # onglet Machines : le nœud de cette machine, les machines appairées et leur état
            return self._envoyer(200, self._vue_machines())
        if chemin == "/api/ressources":                           # ce qui est chargé en mémoire en ce moment (page Santé)
            return self._envoyer(200, _ressources.etat())
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
                return self._envoyer(200, dict(_m.conv_lire(ident), options=_m.options_lire(ident)))          # + les options de cette conversation (accords automatiques, mode…)
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
            return self._envoyer(403, {"erreur": _t("Une sauvegarde se restaure depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin restore.")})
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

    def _api_v1_ecriture(self, methode):
        """PATCH et DELETE n'existent que pour l'API versionnée ; comme tout ce qui modifie, la requête doit venir de la page de Lutin (contrôle de l'origine)."""
        if not self._controle(True):
            return
        if not self.path.split("?")[0].startswith("/api/v1/"):
            _api_v1.discard_body(self)                             # un refus sans lire le corps fait réinitialiser la connexion chez l'appelant, même pour deux octets
            return self._envoyer(404, {"erreur": "introuvable"})
        return _api_v1.dispatch(self, methode)

    def do_PATCH(self):
        return self._api_v1_ecriture("PATCH")

    def do_DELETE(self):
        return self._api_v1_ecriture("DELETE")

    def do_POST(self):
        if not self._controle(True):
            return
        if self.path.split("?")[0].startswith("/api/v1/"):
            return _api_v1.dispatch(self, "POST")
        if self.path.startswith("/api/noeud/relais/"):
            return self._relais("POST")
        if self.path.startswith("/h/"):
            return self._vers_hote("POST")
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
        except (ValueError, RecursionError):
            return self._envoyer(400, {"erreur": "JSON invalide"})
        if not isinstance(donnees, dict):
            return self._envoyer(400, {"erreur": "JSON invalide : un objet est attendu"})
        if self.path == "/api/appairer":                      # le seul POST sans authentification : il sert justement à en obtenir une
            return self._appairer(donnees)
        if self.path == "/api/noeud/appairer":                 # une autre machine échange le code affiché ici contre un jeton de nœud
            return self._noeud_appairer(donnees)
        if self.path == "/api/noeud/chat":                     # ... et l'utilise pour faire tourner le moteur de cette machine
            return self._noeud_chat(donnees)
        if self.path == "/api/noeud/partage":                  # ... ou pour LIRE ce que son propriétaire a accepté de partager (conversations, skills, mémoire) ; jamais écrire
            if not _machines.noeud_jeton_valide(self.headers.get("X-Noeud")):
                return self._envoyer(401, {"erreur": "machine non autorisée"})
            try:
                return self._envoyer(200, _machines.noeud_partager(str(donnees.get("genre", "")), donnees))
            except PermissionError:
                return self._envoyer(403, {"erreur": "ce nœud ne partage pas cela"})
            except (ValueError, OSError) as e:
                return self._envoyer(400, {"erreur": str(e)})
        if self.path == "/api/noeud/capacites":                # ... ou pour savoir ce qu'un de ses modèles sait faire (outils, images, réflexion)
            if not _machines.noeud_jeton_valide(self.headers.get("X-Noeud")):
                return self._envoyer(401, {"erreur": "machine non autorisée"})
            mo = _moteurs.par_id(_m.reglages().get("moteur") or _moteurs.OLLAMA)
            return self._envoyer(200, {"capacites": _machines.noeud_capacites(mo, donnees.get("modele"))})
        if self.path == "/api/noeud/eteindre":                 # ... ou, si le propriétaire l'a autorisé, pour l'éteindre (30 s, annulable, journalisé)
            return self._noeud_eteindre(donnees)
        if self.path == "/api/noeud/maj":                      # ... ou, si le propriétaire l'a autorisé, pour mettre Lutin à jour ici (puis redémarrage si Lutin est supervisé)
            return self._noeud_maj()
        if self.path == "/api/noeud/demande":                  # ... ou pour DEMANDER un droit (rien n'est accordé : le propriétaire de cette machine répond)
            nom = _machines.noeud_jeton_valide(self.headers.get("X-Noeud"))
            if not nom:
                return self._envoyer(401, {"erreur": "machine non autorisée"})
            try:
                return self._envoyer(200, dict(_machines.noeud_demander(nom, str(donnees.get("droit", ""))), ok=True))
            except ValueError as e:
                return self._envoyer(400, {"erreur": str(e)})
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
                if not self._configurateur():
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
            if self.path == "/api/epingler" and str(donnees.get("id", "")) in _m.TOURS_ACTIFS:
                return self._envoyer(409, {"erreur": _t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")})
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
            if self.path == "/api/embeddings-installer":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("L'installation d'un modèle se lance depuis cette machine.")})
                return self._envoyer(200, _embeddings.demarrer_installation())
            if self.path == "/api/mission-action":                   # pause, reprise, arrêt d'une mission : comme envoyer un message, pour qui peut discuter
                try:
                    return self._envoyer(200, _mission.action(str(donnees.get("action", "")), donnees))
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path in ("/api/conversation-dossiers", "/api/conversation-dossier-ouvrir"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                try:
                    ident = str(donnees.get("id", ""))
                    if self.path == "/api/conversation-dossiers":
                        return self._envoyer(200, {"dossiers": _fichiers.dossiers_conversation(ident), "ouverture_possible": _fichiers.ouverture_possible()})
                    return self._envoyer(200, _fichiers.ouvrir_dossier_conversation(ident, str(donnees.get("chemin", ""))))
                except (ValueError, OSError) as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path in ("/api/fichiers-crees-supprimer", "/api/fichiers-crees-dossier"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                try:
                    if self.path == "/api/fichiers-crees-dossier":
                        return self._envoyer(200, _fichiers.ouvrir_dossier(str(donnees.get("id", ""))))
                    ids = donnees.get("ids")
                    return self._envoyer(200, _fichiers.supprimer_selection([str(i) for i in ids][:2000] if isinstance(ids, list) else []))
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path == "/api/piece-ouvrir":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("L'ouverture d'un fichier se fait depuis cette machine : télécharge-le plutôt.")})
                try:
                    return self._envoyer(200, _fichiers.piece_ouvrir(str(donnees.get("id", "")), str(donnees.get("nom", ""))))
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path in ("/api/fichier-ouvrir", "/api/fichier-supprimer", "/api/media-supprimer") and not self._configurateur():
                return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})          # un appareil appairé ne supprime ni n'ouvre rien sur la machine
            if self.path in ("/api/fichier-ouvrir", "/api/fichier-supprimer"):
                try:
                    f = _fichiers.ouvrir if self.path == "/api/fichier-ouvrir" else _fichiers.supprimer
                    return self._envoyer(200, f(str(donnees.get("conversation", "")), str(donnees.get("id", ""))))
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path == "/api/media-supprimer":
                return self._envoyer(200, _m.supprimer_media(str(donnees.get("conversation", "")), str(donnees.get("id", ""))))
            if self.path == "/api/conversation-options":
                ident = str(donnees.get("conversation", ""))
                if not _m.conv_chemin(ident).exists():
                    return self._envoyer(404, {"erreur": _t("Conversation inconnue.")})
                return self._envoyer(200, {"options": _m.options_ecrire(ident, donnees.get("options"))})
            if self.path == "/api/epingler-message":
                return self._envoyer(200, _m.epingler_message(str(donnees.get("conversation", "")), donnees.get("index"), donnees.get("epingle")))
            if self.path in ("/api/addon-activer", "/api/addon-reglages", "/api/addon-verifier", "/api/addon-correction", "/api/addon-flux", "/api/addon-flux-restaurer", "/api/addon-action", "/api/fond-creer", "/api/fond-action"):
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
                    if self.path == "/api/addon-action":
                        return self._envoyer(200, _addons.action(str(donnees.get("id", "")), donnees.get("action", ""), donnees))
                    if self.path == "/api/fond-creer":
                        return self._envoyer(200, _fond.creer(donnees.get("nom"), donnees.get("dossier"), donnees.get("motifs"), donnees.get("consigne"), bool(donnees.get("regulier")), donnees.get("intervalle_h", 24), bool(donnees.get("essai"))))
                    return self._envoyer(200, _fond.action(str(donnees.get("id", "")), str(donnees.get("action", ""))))
                except (_addons.ErreurAddon, ValueError) as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path == "/api/travaux-apercu":
                return self._envoyer(200, _m.apercu_travail(str(donnees.get("id", ""))))
            if self.path in ("/api/dossier-modeles-analyse", "/api/dossier-modeles-copie", "/api/redemarrer-ollama"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Le dossier des modèles se change depuis cette machine.")})
                from . import locations
                if self.path == "/api/dossier-modeles-analyse":
                    return self._envoyer(200, locations.analyse_dossier(str(donnees.get("chemin", ""))))
                if self.path == "/api/dossier-modeles-copie":
                    return self._envoyer(200, locations.copier_modeles(str(donnees.get("chemin", ""))))
                return self._envoyer(200, {"message": _m.redemarrer_ollama()})
            if self.path == "/api/dossier-modeles":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Le dossier des modèles se change depuis cette machine.")})
                from . import locations
                return self._envoyer(200, {"dossier": str(locations.definir_dossier_modeles(str(donnees.get("chemin", "")))), "note": _t("Les modèles déjà téléchargés ne sont pas déplacés : déplace-les à la main dans le nouveau dossier, ou retélécharge-les. Redémarre Ollama (quitte-le puis relance-le) pour qu'il utilise le nouveau dossier.")})
            if self.path == "/api/travaux-choisir":
                return self._envoyer(200, _m.choisir_travail(str(donnees.get("id", ""))))
            if self.path in ("/api/travaux-ajouter", "/api/travaux-retirer", "/api/travaux-deplacer", "/api/travaux-chemin"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": "Les dossiers de travail se gèrent depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin workspaces."})
                if self.path == "/api/travaux-ajouter":
                    return self._envoyer(200, _m.ajouter_travail(str(donnees.get("chemin", "")), str(donnees.get("nom", ""))))
                if self.path == "/api/travaux-deplacer":
                    return self._envoyer(200, _m.deplacer_travail(str(donnees.get("id", "")), str(donnees.get("parent", "")), str(donnees.get("nom", ""))))
                if self.path == "/api/travaux-chemin":
                    return self._envoyer(200, _m.changer_chemin_travail(str(donnees.get("id", "")), str(donnees.get("chemin", ""))))
                return self._envoyer(200, _m.retirer_travail(str(donnees.get("id", "")), bool(donnees.get("nettoyer"))))
            if self.path in ("/api/reprise-detecter", "/api/reprise"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("La reprise des données d'un autre assistant se fait depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin migrate.")})
                if self.path == "/api/reprise-detecter":
                    return self._envoyer(200, _m.reprise_detecter(str(donnees.get("chemin", "")), str(donnees.get("dossier_skills", ""))))
                return self._envoyer(200, _m.reprise_importer(str(donnees.get("chemin", "")), [str(c) for c in (donnees.get("choix") or [])], str(donnees.get("dossier_skills", "")), bool(donnees.get("ecraser")), str(donnees.get("cible", ""))))
            if self.path == "/api/importer-claude":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Un projet Claude s'importe depuis cette machine (niveau « cette machine seulement ») ou avec la commande lutin import-project.")})
                return self._envoyer(200, _m.importer_projet_claude(str(donnees.get("chemin", "")), str(donnees.get("mode", "")), str(donnees.get("vers", "")), str(donnees.get("nom", ""))))
            if self.path in ("/api/notifications-ajouter", "/api/notifications-supprimer", "/api/notifications-tester"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Les notifications se règlent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                if self.path == "/api/notifications-ajouter":
                    return self._envoyer(200, {"canaux": _notif.ajouter(donnees.get("nom"), str(donnees.get("type", "")), donnees.get("params"))})
                if self.path == "/api/notifications-supprimer":
                    return self._envoyer(200, {"canaux": _notif.supprimer(str(donnees.get("id", "")))})
                return self._envoyer(200, _notif.tester(str(donnees.get("id", ""))))
            if self.path.startswith(("/api/github-", "/api/skills-tiers-")):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se règle depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                return self._skills_tiers_ecrire(self.path, donnees)
            if self.path in ("/api/planifie-ajouter", "/api/planifie-modifier", "/api/planifie-arreter", "/api/planifie-supprimer", "/api/planifie-activer", "/api/planifie-lancer", "/api/planifie-notifier"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Les tâches planifiées se gèrent depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                ident = str(donnees.get("id", ""))
                if self.path == "/api/planifie-ajouter":
                    return self._envoyer(200, _plan.ajouter(donnees.get("nom"), donnees.get("prompt"), donnees.get("heure"), donnees.get("jours"), donnees.get("travail"), donnees.get("notifier"), donnees.get("date")))
                if self.path == "/api/planifie-modifier":
                    return self._envoyer(200, _plan.changer(ident, donnees.get("nom"), donnees.get("prompt"), donnees.get("heure"), donnees.get("jours"), donnees.get("travail"), donnees.get("notifier"), donnees.get("date")))
                if self.path == "/api/planifie-arreter":
                    return self._envoyer(200, _plan.arreter(ident))
                if self.path == "/api/planifie-notifier":
                    return self._envoyer(200, _plan.definir_notification(ident, donnees.get("canal")))
                if self.path == "/api/planifie-supprimer":
                    return self._envoyer(200, _plan.supprimer(ident, bool(donnees.get("conversation"))))
                if self.path == "/api/planifie-activer":
                    return self._envoyer(200, _plan.modifier(ident, actif=bool(donnees.get("actif"))))
                if ident in _plan.EN_COURS:
                    raise ValueError(_t("Cette tâche travaille déjà."))
                if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
                    raise ValueError(_t("Une réponse est déjà en cours : attends sa fin."))
                threading.Thread(target=lambda: _plan.executer(ident), daemon=True, name="planifie-lancer").start()
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/calibrage":
                action = str(donnees.get("action", ""))
                if action == "start":
                    return self._envoyer(200, _calibrage.lancer())
                if action == "cancel":
                    return self._envoyer(200, _calibrage.annuler())
                if action == "apply":
                    return self._envoyer(200, _calibrage.appliquer())
                return self._envoyer(400, {"erreur": _t("Action inconnue.")})
            if self.path == "/api/conseil-machine":
                action = str(donnees.get("action", ""))
                if action == "ignorer":
                    _m.enregistrer_reglages({"conseil_machine": False})
                    return self._envoyer(200, {"ok": True})
                if action == "appliquer":
                    changements = _conseil_machine.appliquer(_adequation.profil_pret(), _m.reglages())
                    if changements:
                        _m.enregistrer_reglages(changements)
                    return self._envoyer(200, {"ok": True, "appliques": changements})
                return self._envoyer(400, {"erreur": _t("Action inconnue.")})
            if self.path == "/api/bench-serie":
                return self._envoyer(200, _m.lancer_bench_serie([str(x) for x in (donnees.get("modeles") or [])][:8], bool(donnees.get("rapide"))))
            if self.path == "/api/bench":
                return self._envoyer(200, _m.lancer_bench(str(donnees.get("modele", "")), bool(donnees.get("rapide"))))
            if self.path == "/api/version-ignorer":
                chemin = os.environ.get("LUTIN_VERSION_CACHE")
                if not chemin:
                    raise ValueError("Pas de vérification de version dans ce mode de lancement.")
                from . import updates
                updates.ignorer_version(chemin, str(donnees.get("version", ""))[:40])
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/verifier-lutin":                    # bouton « Vérifier les mises à jour » : une requête GitHub, tout de suite
                chemin = os.environ.get("LUTIN_VERSION_CACHE")
                if not chemin:
                    return self._envoyer(400, {"erreur": _t("Pas de vérification de version dans ce mode de lancement.")})
                from . import updates
                avant = updates.lire_fichier_version(chemin).get("date") or 0
                d = updates.verifier_lutin({"cache": str(Path(chemin).parent)}, force=True)
                if (d.get("date") or 0) <= avant:
                    return self._envoyer(503, {"erreur": _t("Impossible de joindre GitHub : {}").format(d.get("erreur") or "?"), "actuelle": _m.VERSION})
                return self._envoyer(200, {"actuelle": _m.VERSION, "derniere": updates.lire_fichier_version(chemin).get("version", ""), "nouvelle": _m.nouvelle_version_lutin()})
            if self.path == "/api/langue":
                try:
                    return self._envoyer(200, {"langue": _i18n.definir(str(donnees.get("valeur", "")).strip().lower())})
                except ValueError:
                    raise ValueError("Langue inconnue (fr, en ou auto).")
            if self.path == "/api/hors-ligne":
                voulu = bool(donnees.get("actif"))
                if not voulu and not self._configurateur():
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
                _m.repondre_attente(str(donnees.get("id", "")), donnees.get("ok"), bool(donnees.get("reactiver")))
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/reglages":
                rep = _m.enregistrer_reglages(donnees)
                if donnees.get("cluster") is False:
                    _machines.vider_listes()          # mode multi-machines éteint : plus aucun modèle ni conversation distante gardé
                return self._envoyer(200, rep)
            if self.path == "/api/memoire":
                _m.ecrire_memoire(str(donnees.get("fichier", "")), str(donnees.get("texte", "")))
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/skills":
                return self._envoyer(200, _m.ecrire_skill(str(donnees.get("nom", "")), str(donnees.get("texte", ""))))
            if self.path == "/api/skills-supprimer":
                return self._envoyer(200, _m.supprimer_skill(str(donnees.get("nom", ""))))
            if self.path == "/api/nouvelle":
                return self._envoyer(200, _m.conv_nouvelle())
            if self.path in ("/api/supprimer", "/api/renommer", "/api/epingler") and str(donnees.get("id", "")) in _m.TOURS_ACTIFS:
                return self._envoyer(409, {"erreur": _t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")})          # sinon la fin de la réponse réécrirait la conversation par-dessus
            if self.path == "/api/supprimer":
                _mission.oublier_conversation(str(donnees.get("id", "")))                  # sa mission, s'il y en a une, s'arrête avec elle
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
            if self.path == "/api/admin-distance":
                if not self._configurateur_strict():
                    return self._envoyer(403, {"erreur": _t("L'administration à distance s'active ou se retire depuis cette machine seulement (ou avec la commande lutin security).")})
                if _acces.en_docker():
                    return self._envoyer(400, {"erreur": _t("Dans Docker, l'administration à distance se règle avec la variable LUTIN_ADMIN_TOUS du conteneur (docs/DOCKER.md).")})
                cfg = _m.config_lue()
                cfg["admin_a_distance"] = bool(donnees.get("actif"))
                _m.config_ecrire(cfg)
                _m.journaliser("Administration à distance {}.".format("ouverte" if cfg["admin_a_distance"] else "fermée"))
                return self._envoyer(200, {"actif": cfg["admin_a_distance"]})
            if self.path == "/api/web-recherche-config":               # l'adresse de SearXNG (seul hôte local que la recherche peut joindre) et les clés d'API : comme les connecteurs MCP (cette machine, ou LUTIN_ADMIN_TOUS / LUTIN_ADMINS)
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Régler la recherche web (adresse de SearXNG, clés d'API) est verrouillé depuis cet appareil. Depuis la machine elle-même c'est toujours possible ; en Docker ou depuis un autre appareil, ajoute LUTIN_ADMIN_TOUS=1 (ou ton nom dans LUTIN_ADMINS) au docker-compose, puis redémarre.")})
                try:
                    vue = _recherche.enregistrer(**{k: donnees[k] for k in ("searxng", "brave_cle", "tavily_cle", "exa_cle", "perplexity_cle") if k in donnees})
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
                return self._envoyer(200, dict(vue, moteurs=_m.etat_moteurs_recherche(), modifiable=True))
            if self.path == "/api/web-recherche-test":                 # interroge chaque moteur séparément et dit lequel marche
                return self._envoyer(200, {"resultats": _m.tester_moteurs_recherche()})
            if self.path.startswith("/api/machines-"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Ajouter une machine, ou prêter le moteur de celle-ci, se fait depuis cette machine (ou par un administrateur déclaré).")})
                try:
                    return self._envoyer(200, self._machines(self.path[len("/api/machines-"):], donnees))
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path == "/api/observatoire-vider":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se règle depuis cette machine elle-même.")})
                _observatoire.vider()
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/sorties-vider":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se règle depuis cette machine elle-même.")})
                _sorties.vider()
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/web-apercu":                          # /web : les résultats BRUTS d'une recherche, sans modèle ; la requête est nettoyée comme pour le modèle
                requete = str(donnees.get("q") or "").strip()[:300]
                if len(requete) < 2:
                    return self._envoyer(400, {"erreur": _t("Écris quelques mots à chercher, par exemple /web prix du kWh en France.")})
                propre, retire = _sorties.nettoyer_requete(requete)
                trouves, raisons = _web.chercher_resultats(propre or requete, 8) if propre else ([], [_t("requête vide une fois les données personnelles retirées")])
                return self._envoyer(200, {"requete": propre, "retire": retire, "raisons": raisons,
                                           "resultats": [{"titre": x.get("titre", ""), "url": x.get("url", ""), "extrait": str(x.get("extrait", ""))[:300], "date": x.get("date", ""), "source": x.get("source", ""),
                                                          "domaine": _recherche.domaine(x.get("url", ""))} for x in trouves]})
            if self.path == "/api/moteurs-dossier":                    # le dossier où tous les moteurs s'installent (comme le dossier des modèles)
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Installer, démarrer ou régler un moteur se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                try:
                    _llamacpp.regler_dossier_moteurs(donnees.get("dossier"))
                except _llamacpp.ErreurMoteur as e:
                    return self._envoyer(400, {"erreur": str(e)})
                return self._envoyer(200, {"ok": True, "dossier_moteurs": _llamacpp.vue_dossier_moteurs()})
            if self.path.startswith("/api/moteur-"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Installer, démarrer ou régler un moteur se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                mo = _moteurs.MOTEURS.get(str(donnees.get("moteur", "")))
                if mo is None:
                    return self._envoyer(400, {"erreur": _t("Moteur inconnu.")})
                action = self.path[len("/api/moteur-"):]
                try:
                    if action == "action":
                        voulue = str(donnees.get("action", ""))
                        possible = (mo.actions().get(voulue) or {})
                        if voulue not in _moteurs.ACTIONS or not possible.get("possible"):
                            return self._envoyer(400, {"erreur": possible.get("raison") or _t("Cette action n'est pas possible avec ce moteur.")})
                        return self._envoyer(200, {"tache": _moteurs.lancer_tache(mo, voulue)})
                    if action == "annuler":
                        return self._envoyer(200, {"annule": _moteurs.annuler_tache(mo.id)})
                    if action == "regler":
                        if "dossier" in donnees:
                            _llamacpp.regler_dossier(mo.id, donnees.get("dossier"))
                        if "dossier_modeles" in donnees:
                            _llamacpp.regler_dossier_modeles(mo.id, donnees.get("dossier_modeles"))
                        serveur_regle = _llamacpp.regler_serveur(mo.id, donnees)          # Colibri : choix du serveur, dossier du modèle, port
                        avance = _llamacpp.regler_avance(mo.id, {k: donnees[k] for k in ("routeur", "modeles_max", "n_cpu_moe", "version_epinglee") if k in donnees})
                        if not mo.adresse_modifiable:
                            if avance or "dossier" in donnees or "dossier_modeles" in donnees:
                                return self._envoyer(200, {"ok": True})
                            return self._envoyer(400, {"erreur": _t("Ce moteur n'a pas d'adresse à régler.")})
                        if mo.id == "llamacpp" and "url" not in donnees and "variante" not in donnees and avance:
                            return self._envoyer(200, {"ok": True})
                        if serveur_regle and "url" not in donnees and "cle" not in donnees:
                            return self._envoyer(200, {"ok": True})
                        _llamacpp.regler(mo.id, donnees.get("url"), donnees.get("cle"), variante=donnees.get("variante") if donnees.get("variante") in ("auto", "cuda", "vulkan", "cpu", "metal") else None)
                        return self._envoyer(200, {"ok": True})
                    if action == "telecharger":
                        repo, fichier = str(donnees.get("repo", "")), str(donnees.get("fichier", ""))
                        if not mo.telechargeable()["possible"]:
                            return self._envoyer(400, {"erreur": mo.telechargeable()["raison"]})
                        return self._envoyer(200, {"tache": _moteurs.lancer_tache(mo, "telecharger", lambda a, progression: mo.telecharger_modele(repo, fichier, progression))})
                    if action == "supprimer":
                        mo.supprimer_modele(str(donnees.get("nom", "")))
                        return self._envoyer(200, {"ok": True})
                except (ValueError, OSError) as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path in ("/api/outils-installer", "/api/outils-desinstaller"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Installer un programme se fait depuis la machine de Lutin (ou par un administrateur déclaré).")})
                try:
                    if self.path.endswith("installer") and not self.path.endswith("desinstaller"):
                        _outils_externes.installer(str(donnees.get("nom", "")))
                    else:
                        _outils_externes.desinstaller(str(donnees.get("nom", "")))
                    return self._envoyer(200, {"ok": True})
                except ValueError as e:
                    return self._envoyer(400, {"erreur": str(e)})
            if self.path.startswith("/api/mcp-"):
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Brancher un connecteur lance un programme : ça se fait depuis la machine de Lutin (ou par un administrateur déclaré).")})
                action = self.path[len("/api/mcp-"):]
                if action == "ajouter":
                    ident = _mcp.ajouter(str(donnees.get("nom", "")), donnees.get("commande"), donnees.get("url", ""), donnees.get("env"), donnees.get("entetes"))
                    return self._envoyer(200, {"id": ident})
                if action == "catalogue-installer":
                    return self._envoyer(200, _mcp_catalogue.installer(str(donnees.get("id", "")), donnees.get("saisie") or {}))
                if action == "demo":
                    ident = _mcp.ajouter(_t("Démonstration"), [sys.executable, "-m", "lutin.mcp_demo"], "", {"PYTHONPATH": str(Path(__file__).resolve().parent.parent)})
                    return self._envoyer(200, {"id": ident})
                ident = str(donnees.get("id", ""))
                if action == "supprimer":
                    _mcp.supprimer(ident)
                    return self._envoyer(200, {"ok": True})
                if action == "actualiser":
                    return self._envoyer(200, {"outils": _mcp.actualiser(ident)})
                if action == "regler":
                    _mcp.regler(ident, donnees.get("actif"), donnees.get("lecture_seule"), donnees.get("outil"), donnees.get("autorise"), donnees.get("env"), donnees.get("entetes"))
                    return self._envoyer(200, {"ok": True})
            if self.path == "/api/mesurer-moteur":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                if _m.TOURS_ACTIFS:
                    return self._envoyer(409, {"erreur": _t("Une réponse est en cours : attends sa fin avant de mesurer (la mesure occupe le moteur).")})
                if str(donnees.get("moteur", "")) not in _moteurs.MOTEURS:
                    return self._envoyer(400, {"erreur": _t("Moteur inconnu.")})
                mo = _moteurs.par_id(str(donnees["moteur"]))
                modele = str(donnees.get("modele", ""))
                return self._envoyer(200, _mesures.lancer(_m.DONNEES, mo, modele, str(donnees.get("mode", "rapide")), memoire=lambda: _bench_moteurs.memoire_du_moteur(mo.id, modele)))
            if self.path in ("/api/exllamav3-verifier", "/api/lmstudio-verifier", "/api/colibri-verifier"):          # chercher les mises à jour des modèles téléchargés (ExLlamaV3), ou de nouveaux modèles qui tiennent sur cette machine
                genre = self.path[len("/api/"):-len("-verifier")]
                mo = _moteurs.par_id("openai")
                if not {"exllamav3": mo.exllamav3_choisi, "lmstudio": mo.lmstudio_choisi, "colibri": mo.colibri_choisi}[genre]():
                    return self._envoyer(400, {"erreur": _t("Ce serveur n'est pas le serveur choisi.")})
                try:
                    if genre == "exllamav3":
                        from . import exllamav3 as _exl
                        installes = _exl.modeles(mo._dossiers())
                        if str(donnees.get("portee")) == "maj":
                            return self._envoyer(200, _exl_cat.versions_plus_recentes(installes))
                        candidats, deja = _exl_cat.chercher("", "recent", False, 1)["modeles"], {x.get("depot") for x in installes}
                    elif genre == "lmstudio":
                        from . import lmstudio as _lmstudio
                        candidats, deja = _lms_cat.chercher("", "recent", False, 1)["modeles"], {x["nom"].split("/")[-1] for x in (_lmstudio.modeles() if mo._lms() else [])}
                    else:
                        from . import colibri as _colibri
                        installes = _colibri.modeles_installes(mo._dossiers(), mo.modele_colibri())
                        candidats = [m for m in self._catalogue_colibri(mo, installes, "")["modeles"] if not m["installes"]]
                        deja = set()
                    profil = _adequation.profil_pret()
                    propositions = []
                    for m in candidats:
                        ju = m.get("adequation") or (_adequation.evaluer({"go": m["estimation_go"]}, profil) if profil is not None and m.get("estimation_go") else None)
                        if m["id"] in deja or not ju or ju["niveau"] == "trop_gros":
                            continue
                        propositions.append(dict(m, adequation=ju))
                    return self._envoyer(200, {"propositions": propositions[:8]})
                except ValueError as e:
                    return self._envoyer(502, {"erreur": str(e)})
            if self.path == "/api/exllamav3-telecharger":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                mo = _moteurs.par_id("openai")
                if not mo.exllamav3_choisi():
                    return self._envoyer(400, {"erreur": _t("ExLlamaV3 n'est pas le serveur choisi.")})
                depot, revision = str(donnees.get("depot", ""))[:120], str(donnees.get("revision", ""))[:41]
                return self._envoyer(200, _moteurs.lancer_tache(mo, "telecharger:" + depot + ("@" + revision if revision else "")))
            if self.path == "/api/lmstudio-telecharger":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                mo = _moteurs.par_id("openai")
                if not mo.lmstudio_choisi():
                    return self._envoyer(400, {"erreur": _t("LM Studio n'est pas le serveur choisi.")})
                return self._envoyer(200, _moteurs.lancer_tache(mo, "telecharger:" + str(donnees.get("nom", ""))[:121]))
            if self.path == "/api/colibri-preparer":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                mo = _moteurs.par_id("openai")
                if not mo.colibri_choisi():
                    return self._envoyer(400, {"erreur": _t("Colibri n'est pas le serveur choisi.")})
                return self._envoyer(200, _moteurs.lancer_tache(mo, "preparer:" + str(donnees.get("id", ""))[:41]))
            if self.path == "/api/supprimer-modele":
                return self._envoyer(200, _m.supprimer_modele(str(donnees.get("modele", ""))))
            if self.path == "/api/demarrer-ollama":
                return self._envoyer(200, {"message": _m.demarrer_ollama()})
            if self.path == "/api/bench-moteurs":
                if not self._configurateur():
                    return self._envoyer(403, {"erreur": _t("Cela se fait depuis cette machine (niveau « cette machine seulement » ou navigateur de cette machine).")})
                _bench_moteurs.lancer(_m.reglages()["modele"], str(donnees.get("mode", "rapide")), _m.DONNEES, _moteurs.CONTEXTE["profil"]())
                return self._envoyer(200, {"ok": True})
            if self.path == "/api/decharger":                          # décharger une chose de la liste des ressources (modèle d'Ollama, serveur llama.cpp, ComfyUI)
                return self._envoyer(200, _ressources.decharger(donnees.get("id")))
            if self.path == "/api/liberer-vram":
                return self._envoyer(200, _m.liberer_vram(tout=True))
            if self.path == "/api/resumer":
                return self._resumer(donnees)
        except (ValueError, OSError, TypeError, subprocess.SubprocessError) as erreur:
            return self._envoyer(400, {"erreur": str(erreur)})
        return self._envoyer(404, {"erreur": "introuvable"})

    # ---- ce Lutin prête son moteur à une autre machine (voir lutin.machines) ----
    @staticmethod
    def _racines_travail():
        """{id: chemin} des dossiers de travail, et l'identifiant du dossier actif (où les skills s'installent par défaut)."""
        cfg = _m.config_lue()
        actif = _travaux.actif(cfg)
        return {t["id"]: t["chemin"] for t in _travaux.liste(cfg)}, (actif["id"] if actif else "")

    def _skills_tiers_lire(self, chemin):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        un = lambda cle, defaut="": (q.get(cle) or [defaut])[0]  # noqa: E731
        try:
            if chemin == "/api/skills-tiers":                     # tout ce que la page demande en arrivant
                racines, actif = self._racines_travail()
                return self._envoyer(200, {"sources": _skills.sources(), "github": _github.vue(), "travaux": [{"id": i, "nom": Path(c).name or c} for i, c in racines.items()], "actif": actif,
                                           "indexation": {d: dict(e) for d, e in _skills.INDEXATION.items()}, "modifiable": self._configurateur()})
            if chemin == "/api/skills-tiers-chercher":
                depots = [d for d in un("depots").split(",") if d] or [s["depot"] for s in _skills.sources()]
                connus = {s["depot"] for s in _skills.sources()}
                if any(d not in connus for d in depots):
                    return self._envoyer(400, {"erreur": _t("Ce dépôt n'est pas dans ta liste.")})
                return self._envoyer(200, _skills.chercher(un("q"), depots, un("page", "1")))
            if chemin == "/api/skills-tiers-depots":
                return self._envoyer(200, {"depots": _skills.chercher_depots(un("q"))})
            if chemin == "/api/skills-tiers-listes":                # les dépôts cités par les listes communautaires
                return self._envoyer(200, {"depots": _skills.depots_recenses(un("q"))})
            if chemin == "/api/skills-tiers-fiche":
                depot = "/".join(_skills.lire_depot(un("depot")))
                if depot not in {s["depot"] for s in _skills.sources()}:
                    return self._envoyer(400, {"erreur": _t("Ce dépôt n'est pas dans ta liste.")})
                return self._envoyer(200, _skills.fiche(depot, un("dir")))
            if chemin == "/api/skills-tiers-installes":
                racines, _ = self._racines_travail()
                liste = _skills.installes(racines)
                return self._envoyer(200, {"installes": _skills.mises_a_jour(liste) if un("verifier") == "1" else liste})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})          # jamais 5xx : une lecture qui échoue (limite de GitHub, réseau) est un refus expliqué, pas une panne de Lutin
        return self._envoyer(404, {"erreur": "introuvable"})

    def _skills_tiers_ecrire(self, chemin, donnees):
        try:
            if chemin == "/api/github-enregistrer":
                return self._envoyer(200, _github.enregistrer(donnees.get("jeton")))
            if chemin == "/api/github-tester":
                return self._envoyer(200, _github.tester(_skills.http_defaut))
            if chemin == "/api/skills-tiers-source":
                if donnees.get("retirer"):
                    return self._envoyer(200, {"sources": _skills.retirer_source(str(donnees.get("depot", "")))})
                return self._envoyer(200, {"sources": _skills.ajouter_source(donnees.get("depot"))})
            racines, actif = self._racines_travail()
            if chemin == "/api/skills-tiers-indexer":
                depot = str(donnees.get("depot", ""))
                if depot not in {s["depot"] for s in _skills.sources()}:
                    return self._envoyer(400, {"erreur": _t("Ce dépôt n'est pas dans ta liste.")})
                if not (_skills.INDEXATION.get(depot) or {}).get("fini", True):
                    return self._envoyer(200, {"deja": True})
                threading.Thread(target=lambda: _skills.indexer(depot), daemon=True, name="skills-indexation").start()
                return self._envoyer(200, {"ok": True})
            travail = str(donnees.get("travail") or actif)
            if travail not in racines:
                return self._envoyer(400, {"erreur": _t("Choisis le dossier de travail où installer le skill (Réglages > Dossiers).")})
            if chemin in ("/api/skills-tiers-installer", "/api/skills-tiers-maj"):
                if chemin == "/api/skills-tiers-maj":
                    s = next((x for x in _skills.installes({travail: racines[travail]}) if x["nom"] == str(donnees.get("nom", ""))), None)
                    if s is None:
                        return self._envoyer(400, {"erreur": _t("Ce skill n'a pas été installé par Lutin.")})
                    depot, dossier, remplacer, nom = s["depot"], s["dir"], True, s["nom"]
                else:
                    depot, dossier, remplacer, nom = "/".join(_skills.lire_depot(donnees.get("depot"))), str(donnees.get("dir", "")), False, ""
                    if depot not in {x["depot"] for x in _skills.sources()}:
                        return self._envoyer(400, {"erreur": _t("Ce dépôt n'est pas dans ta liste.")})
                r = _skills.installer(depot, dossier, racines[travail], danger_ok=bool(donnees.get("danger_ok")), licence_ok=bool(donnees.get("licence_ok")), remplacer=remplacer, nom=nom)
                _m.journaliser("Skill tiers installé : {} ({}, {}).".format(r["nom"], depot, dossier))
                return self._envoyer(200, r)
            if chemin == "/api/skills-tiers-retirer":
                _skills.retirer(racines[travail], str(donnees.get("nom", "")))
                _m.journaliser("Skill tiers retiré : {}.".format(str(donnees.get("nom", ""))[:60]))
                return self._envoyer(200, {"ok": True})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})          # jamais 5xx : une lecture qui échoue (limite de GitHub, réseau) est un refus expliqué, pas une panne de Lutin
        return self._envoyer(404, {"erreur": "introuvable"})

    def _modeles_serveur_gere(self, chemin):
        """ExLlamaV3, LM Studio et Colibri : les mêmes routes (modèles, catalogue, quantifications), les mêmes réponses — la page Modèles est donc la même pour les trois."""
        genre, route = ROUTES_MODELES_GERES[chemin.split("?")[0]]
        mo = _moteurs.par_id("openai")
        choisi = {"exllamav3": mo.exllamav3_choisi, "lmstudio": mo.lmstudio_choisi, "colibri": mo.colibri_choisi}[genre]()
        nom = {"exllamav3": "ExLlamaV3", "lmstudio": "LM Studio", "colibri": "Colibri"}[genre]
        if not choisi:
            return self._envoyer(404, {"erreur": _t("{} n'est pas le serveur choisi.").format(nom)})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        profil = _adequation.profil_pret()
        juger = (lambda go: _adequation.evaluer({"go": go}, profil)) if profil is not None else (lambda go: None)
        actif = _m.reglages().get("modele")
        try:
            if genre == "exllamav3":
                from . import exllamav3 as _exl
                installes = _exl.modeles(mo._dossiers())
                present = mo._exl() is not None
                dossier = str(_exl.dossier_modeles(mo._dossiers()))
                catalogue, quants = _exl_cat.chercher, _exl_cat.quantifications
            elif genre == "lmstudio":
                from . import lmstudio as _lmstudio
                present = mo._lms() is not None
                installes = _lmstudio.modeles() if present else []
                dossier = str(_lmstudio.dossier_modeles())
                catalogue, quants = _lms_cat.chercher, _lms_cat.quantifications
            else:
                from . import colibri as _colibri
                present = _colibri.installee(mo._dossiers()) is not None
                installes = _colibri.modeles_installes(mo._dossiers(), mo.modele_colibri()) if present else []
                dossier = str(_colibri.dossier_modeles(mo._dossiers()))
                catalogue = quants = None
            if route == "modeles":
                reponse = {"modeles": [dict(x, adequation=juger(x["taille_go"]) if x.get("taille_go") else None, utilise=(x["nom"] == actif) if genre != "colibri" else True) for x in installes],
                           "installe": present, "dossier": dossier, "actif": bool(mo.modeles()["actif"]) if present else False,
                           "maj": genre == "exllamav3", "nom": nom, "statut": mo.statut().get("detail", "") if present else "", "demarrer": mo.actions().get("demarrer") if present else None}
                return self._envoyer(200, reponse)
            if route == "catalogue":
                if genre == "colibri":
                    return self._envoyer(200, self._catalogue_colibri(mo, installes, (q.get("q") or [""])[0]))
                r = catalogue((q.get("q") or [""])[0], (q.get("tri") or ["recent"])[0], (q.get("communaute") or ["0"])[0] == "1", (q.get("page") or ["1"])[0])
                deja = {}
                for x in installes:
                    deja.setdefault(x.get("depot", "") or x["nom"], []).append(x.get("revision") or "main")
                for m in r["modeles"]:
                    m["adequation"] = juger(m["estimation_go"]) if m.get("estimation_go") else None
                    m["installes"] = deja.get(m["id"], [])
                return self._envoyer(200, r)
            depot = (q.get("depot") or [""])[0]
            deja = {x.get("revision") or "main" for x in installes if x.get("depot") == depot}
            liste = quants(depot)
            for x in liste:
                x["adequation"] = juger(x["go"]) if x.get("go") else None
                x["installe"] = x["revision"] in deja
            return self._envoyer(200, {"quantifications": liste})
        except ValueError as e:
            return self._envoyer(502, {"erreur": str(e)})

    @staticmethod
    def _catalogue_colibri(mo, installes, q):
        """Le catalogue de Colibri, dans la forme des autres : jugé par Colibri lui-même (« tient » / « ne tient pas »), filtré par le mot cherché."""
        from . import colibri as _colibri
        mots = str(q or "").lower().split()
        sortie = []
        for m in sorted(_colibri.catalogue(mo._dossiers()), key=lambda x: (not x["ok"], x["go"])):
            if mots and not all(w in m["id"].lower() for w in mots):
                continue
            ad = {"niveau": "bien", "texte": _t("Colibri juge que ce modèle tient sur cette machine.")} if m["ok"] else {"niveau": "trop_gros", "texte": m["raison"] or _t("Ne tient pas sur cette machine.")}
            sortie.append({"id": m["id"], "nom": m["id"], "auteur": "colibri", "telechargements": 0, "aime": 0, "maj": "", "capacites": [], "licence": "", "base": "", "estimation_go": m["go"], "adequation": ad,
                           "installes": ["prêt"] if any(m["id"] in x["nom"] for x in installes) else [], "direct": True})
        return {"modeles": sortie, "suite": False}

    def _noeud_etat(self):
        if not _machines.noeud_jeton_valide(self.headers.get("X-Noeud")):
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        mo = _moteurs.par_id(_m.reglages().get("moteur") or _moteurs.OLLAMA)
        return self._envoyer(200, _machines.noeud_etat(mo, mo.modeles(), self.request.getsockname()[0], _machines.noeud_charge(bool(_m.TOURS_ACTIFS), self.NOEUD_ACTIFS["n"]), _machines.noeud_jeton_valide(self.headers.get("X-Noeud")) or ""))

    def _noeud_appairer(self, donnees):
        if not _m.LIMITEUR_PIN.autoriser(self.client_address[0]):
            return self._envoyer(429, {"erreur": "Trop d'essais : attends une minute."})
        try:
            return self._envoyer(200, _machines.noeud_echanger(donnees.get("code"), donnees.get("nom"), self.request.getsockname()[0]))
        except ValueError as e:
            return self._envoyer(403, {"erreur": str(e)})

    def _noeud_eteindre(self, donnees):
        nom = _machines.noeud_jeton_valide(self.headers.get("X-Noeud"))
        if not nom:
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        if not _machines.noeud().get("extinction"):
            return self._envoyer(403, {"erreur": "l'extinction à distance n'est pas autorisée sur cette machine"})
        if donnees.get("annuler"):
            return self._envoyer(200, {"annulee": _alimentation.annuler_extinction(_machines.journaliser)})
        try:
            return self._envoyer(200, {"dans_s": _alimentation.programmer_extinction(nom, journaliser=_machines.journaliser)})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    def _noeud_maj(self):
        if not _machines.noeud_jeton_valide(self.headers.get("X-Noeud")):
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        if not _machines.noeud().get("maj"):
            return self._envoyer(403, {"erreur": "la mise à jour à distance n'est pas autorisée sur cette machine"})
        try:
            _machines.journaliser("mise à jour demandée par une machine appairée")
            return self._envoyer(200, {"ok": True, "maj": _acces.mettre_a_jour()})
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})

    RELAIS_GET = re.compile(r"^/(api/conversation\?id=[0-9a-f]{8}|image/[A-Za-z0-9_.\-]{1,80}|piece/[A-Za-z0-9_.\-]{1,80}(\?nom=[^&\s]{0,300})?|fichier/[0-9a-f]{8}/[A-Za-z0-9_.\-]{1,80})$")
    RELAIS_POST = ("/api/chat", "/api/arreter", "/api/approuver", "/api/annuler-tour", "/api/memoire-choix", "/api/image", "/api/document", "/api/renommer", "/api/epingler", "/api/supprimer")

    def _relais(self, methode):
        """Cette machine (l'hôte) exécute ce qu'une machine appairée lui demande dans une de SES conversations : le tour entier, avec ses modèles, ses outils, ses addons ; les fichiers restent ici.
        Droit « piloter » (décoché par défaut), jeton de nœud, liste blanche de chemins ; les règles de cette machine (dossiers, accords) s'appliquent et rien de ce qui change les accès n'est joignable."""
        def refuser(code, corps):
            if methode == "POST":          # un refus sans lire le corps fait réinitialiser la connexion chez l'appelant : on le lit (borné) puis on le jette
                reste = min(self._taille_corps(), 64 * 1024 * 1024)
                while reste > 0:
                    morceau = self.rfile.read(min(reste, 65536))
                    if not morceau:
                        break
                    reste -= len(morceau)
            return self._envoyer(code, corps)
        nom = _machines.noeud_jeton_valide(self.headers.get("X-Noeud"))
        if not nom:
            return refuser(401, {"erreur": "machine non autorisée"})
        if not _machines.noeud().get("piloter"):
            return refuser(403, {"erreur": _t("Cette machine n'accepte pas de conversations pilotées à distance : son propriétaire doit cocher « Laisser les machines appairées mener des conversations ici » dans l'onglet Machines.")})
        interne = self.path[len("/api/noeud/relais"):]
        chemin = interne.split("?")[0]
        if not (self.RELAIS_GET.match(interne) if methode == "GET" else chemin in self.RELAIS_POST):
            return refuser(404, {"erreur": "chemin inconnu"})
        if chemin == "/api/chat":
            _machines.journaliser("conversation menée ici par {}".format(nom))
        self._via_relais, self.path = nom, interne
        return self.do_GET() if methode == "GET" else self.do_POST()

    def _vers_hote(self, methode):
        """`/h/<machine>/<chemin>` : la page parle à une conversation menée sur l'autre machine ; on transmet sans rien garder ici (la conversation, ses fichiers et ses images restent chez elle)."""
        if not self._authentifie():
            return self._envoyer(401, {"erreur": "authentification requise"})
        if methode == "POST" and not self._jeton_valide():
            return self._envoyer(403, {"erreur": "jeton invalide : recharge la page"})
        reste = self.path[len("/h/"):]
        ident, _, chemin = reste.partition("/")
        chemin = "/" + chemin
        m = _machines.trouver(ident) if _machines.RE_ID.match(ident) else None
        if m is None:
            return self._envoyer(404, {"erreur": _t("Machine inconnue.")})
        if _machines.DERNIER_ETAT.get(ident) not in ("joignable", "operationnel"):
            return self._envoyer(503, {"erreur": _t("La machine « {} » ne répond pas : sa conversation reviendra quand elle sera de nouveau en ligne.").format(m["nom"])})
        corps = None
        if methode == "POST":
            taille = self._taille_corps()
            if taille > 64 * 1024 * 1024:
                return self._envoyer(413, {"erreur": "message trop gros"})
            corps = self.rfile.read(taille)
        try:
            rep = _machines.ouvrir_relais(m, methode, chemin, corps, self.headers.get("Content-Type") or "application/json", self.headers.get("X-Nom") or "")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read(100_000).decode("utf-8", "replace")).get("erreur", "")
            except (ValueError, OSError, AttributeError):
                detail = ""
            return self._envoyer(e.code if e.code in (400, 403, 404, 409, 413, 429) else 502, {"erreur": detail or _t("Cette machine a répondu une erreur ({}).").format(e.code)})
        except (ValueError, urllib.error.URLError, OSError):
            _machines.signaler_panne(m)
            return self._envoyer(502, {"erreur": _t("Impossible de joindre la machine « {} » : elle ne répond plus.").format(m["nom"])})
        with rep:
            self.send_response(rep.status)
            for nom in _machines.ENTETES_RELAIS:
                if rep.headers.get(nom):
                    self.send_header(nom, rep.headers[nom])
            self.end_headers()
            try:
                while True:
                    morceau = rep.read1(8192)
                    if not morceau:
                        break
                    self.wfile.write(morceau)
                    self.wfile.flush()
            except (OSError, ValueError):
                pass                                                 # la page est partie ou la machine s'est tue : le tour, lui, continue chez elle

    NOEUD_PLACES = threading.BoundedSemaphore(2)          # deux demandes de machines à la fois au plus : une seule carte graphique
    NOEUD_ACTIFS = {"n": 0}          # demandes d'autres machines en cours ici (montré dans l'état du nœud)
    ATTENTE_LOCAL_S = 120          # une demande d'une autre machine laisse passer l'utilisateur de CETTE machine : au plus ce temps d'attente avant de passer quand même

    def _laisser_passer_l_utilisateur_local(self):
        """Le moteur est partagé : si quelqu'un utilise Lutin sur cette machine, la demande de l'autre machine attend la fin de son tour (au plus ATTENTE_LOCAL_S), puis passe. Le propriétaire de la carte graphique passe en premier."""
        fin = time.monotonic() + self.ATTENTE_LOCAL_S
        while _m.TOURS_ACTIFS and time.monotonic() < fin:
            time.sleep(0.5)

    def _noeud_chat(self, donnees):
        if not _machines.noeud_jeton_valide(self.headers.get("X-Noeud")):
            return self._envoyer(401, {"erreur": "machine non autorisée"})
        try:
            corps = _machines.corps_autorise(donnees.get("corps"))
        except ValueError as e:
            return self._envoyer(400, {"erreur": str(e)})
        mo = _moteurs.par_id(_m.reglages().get("moteur") or _moteurs.OLLAMA)          # le moteur de CETTE machine : jamais une autre machine (pas de chaîne)
        if corps["model"] not in mo.modeles()["installes"]:
            return self._envoyer(404, {"erreur": "modèle absent de cette machine"})
        if not self.NOEUD_PLACES.acquire(blocking=False):
            return self._envoyer(429, {"erreur": "cette machine répond déjà à d'autres demandes"})
        self.NOEUD_ACTIFS["n"] += 1
        try:
            if not corps.get("stream"):
                self._laisser_passer_l_utilisateur_local()
                return self._envoyer(200, mo.chat(corps, 900))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                self._laisser_passer_l_utilisateur_local()
                with mo.chat_flux(corps, 900) as flux:
                    for e in flux:
                        self.wfile.write(json.dumps(e, ensure_ascii=False).encode("utf-8") + b"\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass          # l'autre machine a coupé (Arrêter) : sortir du « with » ferme le moteur, qui arrête de générer
            except ValueError as e:
                try:
                    self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8") + b"\n")
                except OSError:
                    pass
        finally:
            self.NOEUD_ACTIFS["n"] = max(0, self.NOEUD_ACTIFS["n"] - 1)
            self.NOEUD_PLACES.release()

    def _machines(self, action, donnees):
        """onglet Machines (configurateur seulement) : ajouter, retirer, choisir celle qui répond, prêter le moteur de cette machine."""
        r = _m.reglages()
        if action == "add":
            _machines.ajouter(donnees.get("adresse"), donnees.get("code"), donnees.get("nom", ""), donnees.get("mac", ""))
        elif action == "remove":
            ident = str(donnees.get("id", ""))
            _machines.retirer(ident)
            if r.get("machine") == ident:
                _m.enregistrer_reglages({"machine": ""})
        elif action == "use":
            _m.enregistrer_reglages({"machine": str(donnees.get("id") or "")})
        elif action == "mac":
            _machines.definir_mac(str(donnees.get("id", "")), donnees.get("mac"))
        elif action == "noeud-activer":
            _machines.noeud_activer(bool(donnees.get("actif")), niveau_local=_m.SECURITE.niveau == _sec.LOCAL)
        elif action == "wake":
            return _machines.reveiller(str(donnees.get("id", "")))
        elif action == "shutdown":
            return _machines.eteindre(str(donnees.get("id", "")), bool(donnees.get("annuler")))
        elif action == "update":
            return _machines.mettre_a_jour_distante(str(donnees.get("id", "")))
        elif action == "demander":
            return _machines.demander_droit(str(donnees.get("id", "")), str(donnees.get("droit", "")))
        elif action == "demande-repondre":          # le propriétaire de CETTE machine accepte ou refuse : depuis cette machine seulement
            if not self._configurateur_strict():
                raise ValueError(_t("Cela se règle depuis cette machine elle-même."))
            _machines.noeud_repondre_demande(str(donnees.get("machine", "")), str(donnees.get("droit", "")), bool(donnees.get("accepter")))
        elif action in ("node-shutdown", "node-update", "node-pilot", "autostart", "cancel-local-shutdown"):          # ce qui touche l'extinction ou le démarrage de CETTE machine : depuis cette machine seulement
            if not self._configurateur_strict():
                raise ValueError(_t("Cela se règle depuis cette machine elle-même."))
            if action == "node-shutdown":
                _machines.noeud_autoriser_extinction(bool(donnees.get("actif")))
            elif action == "node-update":
                _machines.noeud_autoriser_maj(bool(donnees.get("actif")))
            elif action == "node-pilot":
                _machines.noeud_autoriser_piloter(bool(donnees.get("actif")))
            elif action == "cancel-local-shutdown":
                return {"annulee": _alimentation.annuler_extinction(_machines.journaliser)}
            elif donnees.get("actif"):
                _alimentation.installer_demarrage()
            else:
                _alimentation.retirer_demarrage()
        elif action == "droit":                                    # ce que CETTE machine partage avec les autres : depuis cette machine seulement
            if not self._configurateur_strict():
                raise ValueError(_t("Cela se règle depuis cette machine elle-même."))
            _machines.noeud_droit(str(donnees.get("droit", "")), bool(donnees.get("actif")))
        elif action == "import-skills":
            return _machines.importer_skills(str(donnees.get("id", "")))
        elif action == "import-memoire":
            return _machines.importer_memoire(str(donnees.get("id", "")))
        elif action == "noeud-code":
            return _machines.noeud_nouveau_code()
        elif action == "noeud-revoquer":
            _machines.noeud_revoquer(str(donnees.get("nom", "")))
        else:
            raise ValueError(_t("Action inconnue."))
        return {"ok": True}

    @staticmethod
    def _vue_machines():
        r = _m.reglages()
        return {"noeud": _machines.noeud_vue(), "machines": _machines.etats(r["modele"], choisie=r.get("machine", "")), "choisie": r.get("machine", ""), "niveau_local": _m.SECURITE.niveau == _sec.LOCAL, "demarrage": _alimentation.etat_demarrage_memo(), "journal": _machines.journal()}

    def _appairer(self, donnees):
        if _m.SECURITE.niveau == _sec.LOCAL:
            return self._envoyer(400, {"erreur": "Cet accès est réservé à cette machine : pas de code à saisir."})
        if not _m.LIMITEUR_PIN.autoriser(self.client_address[0]):
            return self._envoyer(429, {"erreur": "Trop d'essais : attends une minute."})
        nom = donnees.get("nom")
        jeton = _m.APPAREILS.appairer(str(donnees.get("pin", "")), _sec.nom_appareil(nom if isinstance(nom, str) else "", self.headers.get("User-Agent"), self._sur_cette_machine()))
        if not jeton:
            return self._envoyer(403, {"erreur": "Code incorrect ou expiré. Demande-en un nouveau sur l'ordinateur (lutin pin)."})
        return self._envoyer(200, {"ok": True}, en_tetes={"Set-Cookie": _sec.en_tete_set_cookie(jeton, _m.SECURITE.url_publique.startswith("https://"))})

    _flux_v1 = False          # posé par lutin.api_v1 : cette demande de réponse vient de /api/v1, ses refus et ses évènements sont traduits à la frontière

    def _refus_tour(self, statut, message, code):
        """Refus d'une demande de réponse, avant que le flux commence. `code` est le code d'erreur de /api/v1 ; les routes historiques ne renvoient que le message."""
        return self._envoyer(statut, _api_v1.error(code, message) if self._flux_v1 else {"erreur": message})

    def _evenement_flux(self, evenement):
        return _api_v1.event(evenement) if self._flux_v1 else evenement

    def _chat(self, donnees):
        texte = str(donnees.get("message", "")).strip()
        if not texte or len(texte) > 60000:
            return self._refus_tour(400, "Écris un message (60 000 caractères au maximum).", "invalid_request")
        try:
            images = _images.verifier_liste(donnees.get("images"))
            pieces = _pieces.verifier_liste(donnees.get("pieces"))
        except ValueError as erreur:
            return self._refus_tour(400, str(erreur), "invalid_request")
        if self._via_relais:                                      # le tour s'exécute avec les réglages DE CETTE machine : ni modèle, ni mode, ni accords automatiques, ni autre machine imposés de l'extérieur
            donnees = {k: v for k, v in donnees.items() if k not in ("modele", "machine", "mode", "options", "reflexion", "travail")}
        ident = str(donnees.get("conversation") or "")
        with _m.VERROU_TOURS:                                   # trop de réponses en cours : on refuse avant de créer quoi que ce soit
            if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES and ident not in _m.TOURS_ACTIFS:
                return self._refus_tour(429, "Déjà {} réponses en cours : une seule carte graphique, attends la fin de l'une d'elles (ou clique sur Arrêter).".format(len(_m.TOURS_ACTIFS)), "too_many_turns")
        _fond.interrompre_pour_utilisateur(8)                    # le travail de fond cède la place : son document en cours sera refait plus tard
        conv = _m.conv_lire(ident) if ident else _m.conv_nouvelle()

        def abandon():                                            # une demande refusée ne laisse pas une conversation vide dans la liste
            if not ident:
                try:
                    _m.conv_supprimer(conv["id"])
                except (OSError, ValueError):
                    pass
        depuis = donnees.get("remplacer_depuis")
        if depuis is not None:
            try:
                depuis = int(depuis)
            except (TypeError, ValueError):
                abandon()
                return self._refus_tour(400, "Indice de message invalide.", "invalid_request")
            if not (0 <= depuis < len(conv["messages"]) and conv["messages"][depuis].get("role") == "user"):
                abandon()
                return self._refus_tour(400, "Ce message n'existe plus dans la conversation : recharge-la.", "invalid_request")
        if isinstance(donnees.get("options"), dict):
            _m.options_ecrire(conv["id"], donnees["options"])                                  # les options affichées par la page deviennent celles de cette conversation (créée au premier message)
        mode_voulu = _m.options_lire(conv["id"]).get("mode") or (donnees.get("mode") if not isinstance(donnees.get("options"), dict) else None) or _m.reglages()["mode"]
        if mode_voulu == "mission":                                                            # mode « Mission longue » : ce message est le cahier des charges (ou une consigne), la conversation sert de compte rendu
            mission_en_cours = _mission.trouver_pour_conversation(conv["id"])
            if not (mission_en_cours and mission_en_cours["etat"] != "terminee") and conv["id"] in _m.TOURS_ACTIFS:
                return self._refus_tour(409, "Cette conversation est déjà en train de répondre. Attends la fin ou clique sur Arrêter.", "turn_running")
            return self._mission_dans_la_conversation(conv, texte, donnees, mission_en_cours, abandon, not ident)
        stop = threading.Event()
        with _m.VERROU_TOURS:
            if conv["id"] in _m.TOURS_ACTIFS:
                return self._refus_tour(409, "Cette conversation est déjà en train de répondre (autre onglet ou téléphone ?). Attends la fin ou clique sur Arrêter.", "turn_running")
            if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
                abandon()
                return self._refus_tour(429, "Déjà {} réponses en cours : une seule carte graphique, attends la fin de l'une d'elles (ou clique sur Arrêter).".format(len(_m.TOURS_ACTIFS)), "too_many_turns")
            try:
                _m.activer_travail(conv, str(donnees.get("travail") or ""))
            except ValueError as erreur:
                abandon()
                return self._refus_tour(409, str(erreur), "workspace_conflict")
            _m.RACINE_TOURS[conv["id"]] = str(_m.RACINE)
            _m.TOURS_ACTIFS[conv["id"]] = stop
        fin_flux = threading.Event()
        try:
            r = _m.appliquer_options(_m.reglages(), conv["id"])
            for k in ("modele", "reflexion", "mode"):
                if k in donnees and (k == "modele" or not isinstance(donnees.get("options"), dict)):
                    r[k] = donnees[k]
            if "machine" in donnees:          # le modèle choisi dans la liste peut être celui d'une autre machine (« » : cette machine-ci)
                ident = str(donnees.get("machine") or "")
                r["machine"] = ident if ident and _machines.trouver(ident) else ""
            if not _modes.valide(r["mode"]):
                abandon()
                return self._refus_tour(400, "Mode inconnu.", "invalid_request")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")                  # nginx (reverse proxy) n'attend pas la fin de la réponse pour la transmettre
            self.end_headers()

            page_partie, verrou_flux = [False], threading.Lock()
            try:
                self.connection.settimeout(DELAI_ECRITURE_FLUX)
            except (OSError, ValueError):
                pass

            def ecrire(octets):
                # Si la page est fermée ou gelée (onglet en arrière-plan, téléphone verrouillé, proxy qui coupe), le tour continue et la conversation est enregistrée à la fin.
                # Une page qui ne lit plus remplit la mémoire du réseau : sans délai, l'écriture bloquerait et la réponse se figerait avec elle. Au premier échec on arrête d'écrire.
                if page_partie[0]:
                    return
                with verrou_flux:
                    try:
                        self.wfile.write(octets)
                        self.wfile.flush()
                    except (OSError, ValueError):
                        page_partie[0] = True

            def emit(evenement):
                ecrire((json.dumps(self._evenement_flux(_m.traduire_evenement(evenement)), ensure_ascii=False) + "\n").encode("utf-8"))

            def battement():
                while not fin_flux.wait(BATTEMENT_FLUX):                  # une ligne vide (la page l'ignore) : un reverse proxy coupe un flux resté silencieux (modèle qui charge, commande longue, attente d'un accord)
                    ecrire(b"\n")
            threading.Thread(target=battement, daemon=True).start()
            emit({"type": "debut", "conversation": conv["id"]})
            _m.LOCAL_TOUR.stop = stop
            _m.tour(conv, texte, emit, r, stop, depuis, identite=self._identite(), images=images, pieces=pieces)
        finally:
            fin_flux.set()
            with _m.VERROU_TOURS:
                if _m.TOURS_ACTIFS.get(conv["id"]) is stop:          # un tour abandonné (voir arreter_conversation) ne retire pas celui d'une réponse plus récente
                    _m.TOURS_ACTIFS.pop(conv["id"], None)
                    _m.RACINE_TOURS.pop(conv["id"], None)

    def _mission_dans_la_conversation(self, conv, texte, donnees, mission_en_cours, abandon, nouvelle):
        """Mode « Mission longue » : le message lance une mission menée DANS cette conversation, ou, si une mission y est déjà en cours, lui apporte une réponse ou une consigne."""
        opts = _m.options_lire(conv["id"])
        extrait = texte if len(texte) <= 160 else texte[:160] + "…"
        if mission_en_cours and mission_en_cours["etat"] != "terminee":
            try:
                _mission.action("repondre", {"id": mission_en_cours["id"], "texte": texte})
            except ValueError as erreur:
                return self._refus_tour(400, str(erreur), "invalid_request")
            info = _t("✉ Noté, Lutin en tient compte à son prochain tour : {}").format(extrait)
        else:
            autonome = bool(opts.get("auto_ecriture") and opts.get("auto_commandes"))
            nom = " ".join(texte.split()[:6])[:60] or _t("Mission")
            titre_avant = conv.get("titre", "")
            try:
                if titre_avant in ("", "Nouvelle conversation"):
                    conv["titre"] = "🎯 " + nom
                    _m.conv_ecrire(conv)
                nouvelle_mission = _mission.creer(nom, texte, str(donnees.get("travail") or conv.get("travail") or ""), opts.get("mission_duree_h", 8), autonome, conv["id"])
            except ValueError as erreur:
                if nouvelle:
                    abandon()
                elif conv.get("titre") != titre_avant:
                    conv["titre"] = titre_avant
                    _m.conv_ecrire(conv)
                return self._refus_tour(400, str(erreur), "invalid_request")
            info = (_t("🎯 Mission lancée : Lutin travaille seul, jusqu'à {} h, et tu suis tout ici. Pause ou arrêt avec les boutons au-dessus du champ de saisie.") if autonome else
                    _t("🎯 Mission lancée « à blanc » : Lutin montre ce qu'il ferait sans rien écrire ni lancer. Coche Fichiers auto et Commandes auto pour qu'il agisse vraiment (ça compte dès le tour suivant).")).format(nouvelle_mission["duree_h"])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        for evenement in ({"type": "debut", "conversation": conv["id"]}, {"type": "info", "texte": info}, {"type": "fin", "conversation": {"id": conv["id"], "titre": conv.get("titre", "")}}):
            try:
                self.wfile.write((json.dumps(self._evenement_flux(evenement), ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                break

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
        if str(conv.get("titre", "")).startswith("🎯"):
            return self._envoyer(200, {"titre": ""})                                              # une conversation de mission garde le nom de sa mission
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
            "model": _m.modele_annexe(r),
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
