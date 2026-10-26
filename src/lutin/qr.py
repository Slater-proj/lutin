"""Un code QR sans dépendance (mode octets, correction d'erreur M, versions 1 à 10 : jusqu'à 213 octets), pour appairer un téléphone en le visant avec l'appareil photo.

`matrice(texte)` renvoie une liste de lignes de 0 et de 1 (1 = module sombre), SANS la marge blanche (la page l'ajoute). Vérifié contre une bibliothèque de référence par tests/test_qr.py.
"""

# versions 1 à 10, niveau M : (octets de données, octets de correction par bloc, [(nombre de blocs, octets de données par bloc), ...])
VERSIONS = {1: (16, 10, [(1, 16)]), 2: (28, 16, [(1, 28)]), 3: (44, 26, [(1, 44)]), 4: (64, 18, [(2, 32)]), 5: (86, 24, [(2, 43)]), 6: (108, 16, [(4, 27)]),
            7: (124, 18, [(4, 31)]), 8: (154, 22, [(2, 38), (2, 39)]), 9: (182, 22, [(3, 36), (2, 37)]), 10: (216, 26, [(4, 43), (1, 44)])}
ALIGNEMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
CAPACITE_MAX = 213


class TropLong(ValueError):
    pass


# ---- Reed-Solomon sur GF(256), polynôme 0x11D
EXP, LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    EXP[_i], LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def _generateur(n):
    g = [1]
    for i in range(n):
        suivant = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            suivant[j] ^= c
            suivant[j + 1] ^= _mul(c, EXP[i])
        g = suivant
    return g


def _correction(donnees, n):
    g = _generateur(n)
    reste = list(donnees) + [0] * n
    for i in range(len(donnees)):
        c = reste[i]
        if c:
            for j in range(1, len(g)):
                reste[i + j] ^= _mul(g[j], c)
    return reste[len(donnees):]


def _bits_donnees(octets, version):
    capacite = VERSIONS[version][0]
    bits = "0100" + format(len(octets), "016b" if version >= 10 else "08b") + "".join(format(b, "08b") for b in octets)
    bits += "0" * min(4, capacite * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    mots = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    for k in range(capacite - len(mots)):
        mots.append(0xEC if k % 2 == 0 else 0x11)
    return mots


def _mots_finaux(mots, version):
    _, ec, groupes = VERSIONS[version]
    blocs, i = [], 0
    for nombre, taille in groupes:
        for _ in range(nombre):
            blocs.append(mots[i:i + taille])
            i += taille
    corrections = [_correction(b, ec) for b in blocs]
    sortie = []
    for k in range(max(len(b) for b in blocs)):
        for b in blocs:
            if k < len(b):
                sortie.append(b[k])
    for k in range(ec):
        for c in corrections:
            sortie.append(c[k])
    return sortie


def _bch(valeur, generateur, degre):
    r = valeur << degre
    while r.bit_length() > degre:
        r ^= generateur << (r.bit_length() - generateur.bit_length())
    return (valeur << degre) | r


MASQUES = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0, lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
           lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0, lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _fonctions(version):
    """Matrice de base : modules de fonction posés (None = libre pour les données) et le masque des modules réservés."""
    n = 17 + 4 * version
    m = [[None] * n for _ in range(n)]

    def pose(r, c, v):
        if 0 <= r < n and 0 <= c < n:
            m[r][c] = v
    for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):                    # repères de position, avec leur séparateur blanc
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                ext = dr in (-1, 7) or dc in (-1, 7)
                if 0 <= r0 + dr < n and 0 <= c0 + dc < n:
                    centre = 2 <= dr <= 4 and 2 <= dc <= 4
                    bord = dr in (0, 6) or dc in (0, 6)
                    pose(r0 + dr, c0 + dc, 0 if ext else (1 if (bord or centre) else 0))
    for i in range(8, n - 8):                                              # lignes de synchronisation
        m[6][i] = m[i][6] = 1 - i % 2
    pos = ALIGNEMENT[version]
    for r in pos:
        for c in pos:
            if (r, c) in ((6, 6), (6, pos[-1]), (pos[-1], 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 1 if max(abs(dr), abs(dc)) != 1 else 0
    m[n - 8][8] = 1                                                        # module sombre fixe
    for i in range(9):                                                     # zones d'information de format (réservées, remplies plus tard)
        for (r, c) in ((8, i), (i, 8)) + (((8, n - 1 - i), (n - 1 - i, 8)) if i < 8 else ()):
            if m[r][c] is None:
                m[r][c] = 0
    if version >= 7:                                                       # information de version
        info = _bch(version, 0x1F25, 12)
        for i in range(18):
            bit = (info >> i) & 1
            a, b = i // 3, n - 11 + i % 3
            m[a][b] = m[b][a] = bit
    reserve = [[m[r][c] is not None for c in range(n)] for r in range(n)]
    return m, reserve


def _poser_donnees(base, reserve, mots):
    n = len(base)
    m = [ligne[:] for ligne in base]
    bits = "".join(format(b, "08b") for b in mots)
    i, haut, c = 0, True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        lignes = range(n - 1, -1, -1) if haut else range(n)
        for r in lignes:
            for dc in (0, 1):
                col = c - dc
                if not reserve[r][col]:
                    m[r][col] = int(bits[i]) if i < len(bits) else 0
                    i += 1
        haut = not haut
        c -= 2
    return m


def _avec_masque(base, reserve, donnees, masque):
    """Applique le masque aux modules de données, puis écrit l'information de format (deux copies)."""
    n = len(base)
    m = [ligne[:] for ligne in donnees]
    for r in range(n):
        for c in range(n):
            if not reserve[r][c] and MASQUES[masque](r, c):
                m[r][c] ^= 1
    bits = _bch(masque, 0x537, 10) ^ 0x5412          # niveau M = 00, puis le numéro de masque (3 bits)

    def bit(i):
        return (bits >> i) & 1
    for i in range(6):                                # première copie, autour du repère haut-gauche
        m[i][8] = bit(i)
    m[7][8], m[8][8], m[8][7] = bit(6), bit(7), bit(8)
    for i in range(9, 15):
        m[8][14 - i] = bit(i)
    for i in range(8):                                # seconde copie : bas-gauche et haut-droite
        m[8][n - 1 - i] = bit(i)
    for i in range(8, 15):
        m[n - 15 + i][8] = bit(i)
    m[n - 8][8] = 1                                   # le module sombre fixe
    return m


def _penalite(m):
    n = len(m)
    total = 0
    for ligne in (m, [list(x) for x in zip(*m)]):
        for l in ligne:
            serie = 1
            for i in range(1, n):
                if l[i] == l[i - 1]:
                    serie += 1
                else:
                    total += serie - 2 if serie >= 5 else 0
                    serie = 1
            total += serie - 2 if serie >= 5 else 0
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                total += 3
    motif1, motif2 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for ligne in (m, [list(x) for x in zip(*m)]):
        for l in ligne:
            for i in range(n - 10):
                morceau = l[i:i + 11]
                if morceau == motif1 or morceau == motif2:
                    total += 40
    sombres = sum(sum(l) for l in m)
    total += 10 * (abs(sombres * 100 // (n * n) - 50) // 5)
    return total


def matrice(texte):
    """Les lignes (0/1) du code QR de `texte`, sans marge. TropLong au-delà de 213 octets."""
    octets = texte.encode("utf-8")
    version = next((v for v in VERSIONS if len(octets) <= (VERSIONS[v][0] * 8 - (20 if v >= 10 else 12)) // 8), None)
    if version is None:
        raise TropLong("texte trop long pour le code QR ({} octets, {} au plus)".format(len(octets), CAPACITE_MAX))
    base, reserve = _fonctions(version)
    donnees = _poser_donnees(base, reserve, _mots_finaux(_bits_donnees(octets, version), version))
    meilleure = min((_penalite(m), k, m) for k, m in ((k, _avec_masque(base, reserve, donnees, k)) for k in range(8)))
    return meilleure[2]


def matrice_avec_masque(texte, masque, version=None):
    """Pour les tests : la matrice avec un masque imposé (et une version imposée si on veut)."""
    octets = texte.encode("utf-8")
    version = version or next(v for v in VERSIONS if len(octets) <= (VERSIONS[v][0] * 8 - (20 if v >= 10 else 12)) // 8)
    base, reserve = _fonctions(version)
    donnees = _poser_donnees(base, reserve, _mots_finaux(_bits_donnees(octets, version), version))
    return _avec_masque(base, reserve, donnees, masque)
