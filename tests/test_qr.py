"""Le code QR d'appairage : un lecteur écrit ici relit le texte, la correction d'erreur est cohérente, la forme est celle de la norme. (Le code a aussi été vérifié par deux lecteurs indépendants — ZXing et OpenCV —
sur toutes les longueurs de 1 à 213 octets et les huit masques ; ces bibliothèques ne sont pas des dépendances.)"""
import hashlib
import unittest

import context  # noqa: F401
from lutin import qr


def relire(m):
    """Lit le code : format, démasquage, zigzag, désentrelacement, contrôle de la correction d'erreur, puis le texte."""
    n = len(m)
    version = (n - 17) // 4
    base, reserve = qr._fonctions(version)
    bits_format = sum(m[8][n - 1 - i] << i for i in range(8)) | sum(m[n - 15 + i][8] << i for i in range(8, 15))
    masque = None
    for k in range(8):
        if (qr._bch(k, 0x537, 10) ^ 0x5412) == bits_format:
            masque = k
    assert masque is not None, "information de format illisible"
    bits, c, haut = [], n - 1, True
    while c > 0:
        if c == 6:
            c -= 1
        for r in (range(n - 1, -1, -1) if haut else range(n)):
            for dc in (0, 1):
                col = c - dc
                if not reserve[r][col]:
                    bits.append(m[r][col] ^ (1 if qr.MASQUES[masque](r, col) else 0))
        haut, c = not haut, c - 2
    mots = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits) - 7, 8)]
    _, ec, groupes = qr.VERSIONS[version]
    tailles = [t for nombre, t in groupes for _ in range(nombre)]
    blocs = [[] for _ in tailles]
    i = 0
    for k in range(max(tailles)):
        for b, t in enumerate(tailles):
            if k < t:
                blocs[b].append(mots[i])
                i += 1
    corrections = [[] for _ in tailles]
    for k in range(ec):
        for b in range(len(tailles)):
            corrections[b].append(mots[i])
            i += 1
    donnees = []
    for b, cor in zip(blocs, corrections):
        for racine in range(ec):                       # syndromes : le bloc entier s'annule sur α^0 … α^(ec-1)
            valeur = 0
            for coef in b + cor:
                valeur = qr._mul(valeur, qr.EXP[racine]) ^ coef
            assert valeur == 0, "correction d'erreur incohérente"
        donnees += b
    flux = "".join(format(x, "08b") for x in donnees)
    assert flux[:4] == "0100", "mode octets attendu"
    largeur = 16 if version >= 10 else 8
    longueur = int(flux[4:4 + largeur], 2)
    debut = 4 + largeur
    return bytes(int(flux[debut + 8 * k:debut + 8 * k + 8], 2) for k in range(longueur)).decode("utf-8")


class CodeQr(unittest.TestCase):
    def test_on_relit_ce_qu_on_a_ecrit_pour_toutes_les_longueurs(self):
        for longueur in range(1, 214):
            texte = ("pin=%d;" % longueur) + "x" * longueur
            texte = texte[:longueur] if len(texte.encode()) > longueur else texte
            self.assertEqual(relire(qr.matrice(texte)), texte, longueur)

    def test_les_huit_masques_sont_relus(self):
        for masque in range(8):
            self.assertEqual(relire(qr.matrice_avec_masque("http://192.168.1.50:8777/#pin=123456", masque)), "http://192.168.1.50:8777/#pin=123456")

    def test_accents_et_symboles(self):
        for texte in ("é à ü – 日本", "Lutin ✔"):
            self.assertEqual(relire(qr.matrice(texte)), texte)

    def test_forme_de_la_norme(self):
        m = qr.matrice("http://192.168.1.50:8777/#pin=123456")
        self.assertEqual((len(m), {len(l) for l in m}), (29, {29}), "version 3")
        for (r0, c0) in ((0, 0), (0, 22), (22, 0)):                          # trois repères de position
            self.assertEqual([m[r0][c0 + i] for i in range(7)], [1] * 7)
            self.assertEqual([m[r0 + i][c0] for i in range(7)], [1] * 7)
            self.assertEqual(m[r0 + 3][c0 + 3], 1)
            self.assertEqual(m[r0 + 1][c0 + 1], 0)
        self.assertEqual([m[6][i] for i in range(8, 21)], [1, 0] * 6 + [1], "ligne de synchronisation")
        self.assertEqual(m[4 * 3 + 9][8], 1, "module sombre fixe")
        self.assertEqual(m[22][22], 1, "motif d'alignement (centre)")

    def test_une_valeur_connue_ne_change_pas(self):
        m = qr.matrice("http://192.168.1.50:8777/#pin=123456")
        self.assertEqual(hashlib.sha256("".join("".join(map(str, l)) for l in m).encode()).hexdigest(), "af257280aa67efb57220c554096ee9225cdfb51cf23881d1a09a894bf22a5187")

    def test_trop_long(self):
        qr.matrice("x" * 213)
        with self.assertRaises(qr.TropLong):
            qr.matrice("x" * 214)


if __name__ == "__main__":
    unittest.main()
