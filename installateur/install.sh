#!/usr/bin/env bash
# Installe ou met a jour Lutin pour l'utilisateur courant (Linux, macOS) :
#   curl -fsSL https://raw.githubusercontent.com/Slater-proj/lutin/main/installateur/install.sh | bash
# Ce que fait ce script, et rien d'autre :
#   1. verifie Python 3.10 ou plus (il ne l'installe pas : il dit quelle commande lancer)
#   2. cree (ou reutilise) un environnement prive dans ~/.local/share/lutin/venv et y installe Lutin
#      - deja installe a la meme version : il ne change rien et le dit ; version differente : mise a jour
#   3. place la commande « lutin » dans ~/.local/bin
#   4. lance « lutin setup » (sans effet si Lutin est deja configure) sauf avec --sans-setup
# Variable facultative : LUTIN_SOURCE = ce qu'il faut passer a pip (une roue, une adresse) ; par defaut : la derniere publication GitHub de Slater-proj/lutin.
# Facultatives : LUTIN_DOSSIER = ou installer, LUTIN_BIN = ou placer la commande ; options --sans-setup, --sans-path.
set -euo pipefail

SOURCE="${LUTIN_SOURCE:-}"
# Sans LUTIN_SOURCE : la derniere publication de https://github.com/Slater-proj/lutin (jamais le nom nu « lutin » sur PyPI : c'est un autre projet).
MARQUEUR=""
[ -n "$SOURCE" ] || MARQUEUR="github:Slater-proj/lutin"
SETUP=1
PATH_OK=1
for a in "$@"; do
  [ "$a" = "--sans-setup" ] && SETUP=0
  [ "$a" = "--sans-path" ] && PATH_OK=0
done

info()  { printf '\033[36m[Lutin]\033[0m %s\n' "$*"; }
echec() { printf '\033[31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

DONNEES="${LUTIN_DOSSIER:-${XDG_DATA_HOME:-$HOME/.local/share}/lutin}"
VENV="$DONNEES/venv"
BIN="${LUTIN_BIN:-$HOME/.local/bin}"
mkdir -p "$DONNEES" "$BIN"

version_installee() {
  [ -x "$VENV/bin/python" ] || { echo ""; return 0; }
  "$VENV/bin/python" -m lutin --version 2>/dev/null | sed 's/^Lutin *//' || true
}
AVANT="$(version_installee)"

if [ ! -x "$VENV/bin/python" ]; then
  PYTHON=""
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PYTHON="$c"; break; fi
  done
  if [ -z "$PYTHON" ]; then
    echo "Python 3.10 ou plus est requis." >&2
    if command -v apt-get >/dev/null 2>&1; then echo "  Debian / Ubuntu :  sudo apt install python3 python3-venv python3-pip" >&2
    elif command -v dnf >/dev/null 2>&1; then echo "  Fedora :           sudo dnf install python3" >&2
    elif command -v pacman >/dev/null 2>&1; then echo "  Arch :             sudo pacman -S python" >&2
    elif command -v brew >/dev/null 2>&1; then echo "  macOS :            brew install python" >&2
    fi
    exit 1
  fi
  info "Python : $($PYTHON --version)"
  info "Creation de l'environnement prive..."
  "$PYTHON" -m venv "$VENV" || echec "Impossible de creer l'environnement (sur Debian/Ubuntu : sudo apt install python3-venv)."
fi

if [ -n "$MARQUEUR" ]; then
  SOURCE="$("$VENV/bin/python" - <<'PYEOF'
import json, sys, urllib.request
try:
    req = urllib.request.Request("https://api.github.com/repos/Slater-proj/lutin/releases/latest", headers={"User-Agent": "lutin-installation", "Accept": "application/vnd.github+json"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    print(next(a["browser_download_url"] for a in d["assets"] if a["name"].endswith(".whl")))
except Exception as e:
    sys.exit(1)
PYEOF
)" || echec "Impossible de lire la derniere version de Lutin sur GitHub (pas d'internet, ou pas encore de publication) : donne LUTIN_SOURCE=<fichier.whl ou adresse>."
fi
info "Verification de Lutin ($SOURCE)..."
"$VENV/bin/python" -m pip install --upgrade --quiet pip
"$VENV/bin/python" -m pip install --upgrade --quiet "$SOURCE" || echec "pip n'a pas pu installer Lutin ($SOURCE)."
APRES="$(version_installee)"
[ -n "$APRES" ] || echec "Lutin est installe mais ne repond pas (« python -m lutin --version »)."
printf '%s\n' "${MARQUEUR:-$SOURCE}" > "$DONNEES/source.txt"          # pour « lutin update »
if [ -z "$AVANT" ]; then info "Lutin $APRES installe."
elif [ "$AVANT" = "$APRES" ]; then info "Lutin $APRES : deja a jour, rien a faire."
else info "Lutin mis a jour : $AVANT -> $APRES."; fi

ln -sf "$VENV/bin/lutin" "$BIN/lutin"
if [ "$PATH_OK" = 1 ]; then
  case ":$PATH:" in
    *":$BIN:"*) ;;
    *) info "Ajoute ceci a ton ~/.bashrc ou ~/.zshrc pour utiliser « lutin » partout :  export PATH=\"$BIN:\$PATH\"" ;;
  esac
fi

if [ "$SETUP" = 1 ]; then
  # Quand le script arrive par « curl | bash », le clavier n'est pas l'entree standard : on le reprend sur le terminal.
  if [ -t 0 ]; then "$BIN/lutin" setup; elif [ -e /dev/tty ]; then "$BIN/lutin" setup < /dev/tty; else echo "Pour continuer :  lutin setup"; fi
else
  echo "Pour continuer :  lutin setup"
fi
