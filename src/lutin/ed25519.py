"""Signature Ed25519 (RFC 8032) en Python pur : vérifier la signature d'un catalogue sans aucune dépendance.

`verifier` sert à Lutin (≈ 10 ms) ; `cle_publique` et `signer` servent à l'outil de signature (tools/signer_catalogue_moteurs.py) et aux tests. Ce n'est pas un module de chiffrement général :
il n'est pas écrit à temps constant, ce qui est sans importance pour VÉRIFIER une signature (aucun secret en jeu) et acceptable pour signer un catalogue sur sa propre machine."""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
RACINE_M1 = pow(2, (P - 1) // 4, P)
BASE_Y = 4 * pow(5, P - 2, P) % P


def _inverse(x):
    return pow(x, P - 2, P)


def _x_depuis_y(y, signe):
    x2 = (y * y - 1) * _inverse(D * y * y + 1) % P
    if x2 == 0:
        return None if signe else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * RACINE_M1 % P
    if (x * x - x2) % P:
        return None
    return P - x if (x & 1) != signe else x


BASE = None


def _addition(a, b):
    """Addition de deux points en coordonnées étendues (X, Y, Z, T)."""
    a1 = (a[1] - a[0]) * (b[1] - b[0]) % P
    b1 = (a[1] + a[0]) * (b[1] + b[0]) % P
    c1 = 2 * a[3] * b[3] * D % P
    d1 = 2 * a[2] * b[2] % P
    e, f, g, h = b1 - a1, d1 - c1, d1 + c1, b1 + a1
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _multiplier(s, point):
    resultat = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            resultat = _addition(resultat, point)
        point = _addition(point, point)
        s >>= 1
    return resultat


def _egaux(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _compresser(point):
    zi = _inverse(point[2])
    x, y = point[0] * zi % P, point[1] * zi % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompresser(octets):
    if len(octets) != 32:
        return None
    y = int.from_bytes(octets, "little")
    signe = y >> 255
    y &= (1 << 255) - 1
    if y >= P:
        return None
    x = _x_depuis_y(y, signe)
    return None if x is None else (x, y, 1, x * y % P)


def _initialiser():
    global BASE
    x = _x_depuis_y(BASE_Y, 0)
    BASE = (x, BASE_Y, 1, x * BASE_Y % P)


_initialiser()


def _sha512(*morceaux):
    return int.from_bytes(hashlib.sha512(b"".join(morceaux)).digest(), "little")


def _secret(graine):
    h = hashlib.sha512(graine).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def cle_publique(graine):
    """La clé publique (32 octets) de la graine secrète (32 octets)."""
    return _compresser(_multiplier(_secret(graine)[0], BASE))


def signer(graine, message):
    """La signature (64 octets) de `message` (octets)."""
    a, prefixe = _secret(graine)
    publique = _compresser(_multiplier(a, BASE))
    r = _sha512(prefixe, message) % L
    grand_r = _compresser(_multiplier(r, BASE))
    h = _sha512(grand_r, publique, message) % L
    return grand_r + int.to_bytes((r + h * a) % L, 32, "little")


def verifier(publique, message, signature):
    """Vrai seulement si `signature` est la signature valide de `message` par la clé `publique`. Ne lève jamais d'exception : toute entrée mal formée donne False."""
    try:
        if len(publique) != 32 or len(signature) != 64:
            return False
        a = _decompresser(bytes(publique))
        r = _decompresser(bytes(signature[:32]))
        s = int.from_bytes(signature[32:], "little")
        if a is None or r is None or s >= L:
            return False
        h = _sha512(bytes(signature[:32]), bytes(publique), message) % L
        return _egaux(_multiplier(s, BASE), _addition(r, _multiplier(h, a)))
    except (TypeError, ValueError):
        return False
