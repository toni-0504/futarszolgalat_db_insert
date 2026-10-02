"""Modellréteg a futárszolgálathoz.

Az osztályok az adatbázis tábláit képezik le, validálják az adatot (ugyanazok a
szabályok, mint az SQL CHECK-ek), és tartalmazzák az üzleti logikát.
Adatbázisba írás itt NINCS. Az id None, amíg az objektumot valaki el nem mentette.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass, field

JARMUVEK = ("auto", "dron", "bicikli", "motor")
FUTAR_ALLAPOTOK = ("elerheto", "uton", "szunet")
TERMEK_TIPUSOK = ("etel", "ital")
FIZETESI_MODOK = ("keszpenz", "kartya")


class ValidacioHiba(ValueError):
    """Érvénytelen adat a modellben."""


def _ellenoriz(feltetel: bool, uzenet: str) -> None:
    if not feltetel:
        raise ValidacioHiba(uzenet)


# ---------------------------------------------------------------------------
@dataclass
class Allergen:
    nev: str
    kod: int | None = None

    @classmethod
    def sorbol(cls, sor) -> Allergen:
        """sor: sqlite3.Row vagy dict a 'allergen' táblából."""
        return cls(kod=sor["kod"], nev=sor["nev"])


_EMAIL_MINTA = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HASH_ITER = 600_000
MIN_JELSZO_HOSSZ = 8


def jelszo_hashel(jelszo: str) -> str:
    """Sózott PBKDF2 hash 'pbkdf2_sha256$iteráció$só$hash' formában.
    A jelszót SOHA nem tároljuk sima szövegként."""
    so = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", jelszo.encode(), so, _HASH_ITER)
    return f"pbkdf2_sha256${_HASH_ITER}${so.hex()}${h.hex()}"


def jelszo_egyezik(jelszo: str, tarolt_hash: str) -> bool:
    """True, ha a megadott jelszó megfelel a tárolt hash-nek."""
    try:
        _, iteracio, so, h = tarolt_hash.split("$")
        szamolt = hashlib.pbkdf2_hmac("sha256", jelszo.encode(),
                                      bytes.fromhex(so), int(iteracio))
        return hmac.compare_digest(szamolt, bytes.fromhex(h))
    except ValueError:
        return False


@dataclass
class Felhasznalo:
    nev: str
    cim: str
    telszam: str
    email: str
    jelszo_hash: str = field(repr=False)   # az SQL-ben a 'password' oszlopba kerül
    admin: bool = False                    # az SQL-ben: isAdmin
    id: int | None = None

    def __post_init__(self):
        for mezo in ("nev", "cim", "telszam"):
            _ellenoriz(bool(getattr(self, mezo).strip()), f"A(z) {mezo} nem lehet üres.")
        _ellenoriz(isinstance(self.email, str) and isinstance(self.jelszo_hash, str),
                   "Hiányzik az email vagy a jelszo_hash (a régi sorokat ki kell tölteni).")
        self.email = self.email.strip().lower()   # egységes alak: kis- és nagybetű ne számítson
        _ellenoriz(bool(_EMAIL_MINTA.match(self.email)), f"Érvénytelen email: {self.email}")
        _ellenoriz(self.jelszo_hash.startswith("pbkdf2_sha256$"),
                   "A jelszó nincs hash-elve. Új felhasználónál a regisztral() metódust használd, "
                   "régi (sima szöveges) jelszavaknál futtasd a migracio_felhasznalo()-t.")

    @classmethod
    def regisztral(cls, nev: str, cim: str, telszam: str, email: str,
                   jelszo: str, admin: bool = False) -> Felhasznalo:
        """Új felhasználó SIMA jelszóból: ellenőrzi a hosszát, majd hash-eli."""
        _ellenoriz(len(jelszo) >= MIN_JELSZO_HOSSZ,
                   f"A jelszó legalább {MIN_JELSZO_HOSSZ} karakter legyen.")
        return cls(nev, cim, telszam, email, jelszo_hashel(jelszo), admin)

    def jelszo_helyes(self, jelszo: str) -> bool:
        return jelszo_egyezik(jelszo, self.jelszo_hash)

    def jelszo_csere(self, uj_jelszo: str) -> None:
        _ellenoriz(len(uj_jelszo) >= MIN_JELSZO_HOSSZ,
                   f"A jelszó legalább {MIN_JELSZO_HOSSZ} karakter legyen.")
        self.jelszo_hash = jelszo_hashel(uj_jelszo)

    @classmethod
    def sorbol(cls, sor) -> Felhasznalo:
        return cls(id=sor["id"], nev=sor["nev"], cim=sor["cim"], telszam=sor["telszam"],
                   email=sor["email"], jelszo_hash=sor["password"],
                   admin=bool(sor["isAdmin"]))   # NULL (nincs megadva) = nem admin


@dataclass
class Futar:
    nev: str
    telszam: str
    jarmu: str
    hatosugar_km: int
    ember: int = 0
    allapot: str = "elerheto"
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(self.jarmu in JARMUVEK, f"Érvénytelen jármű: {self.jarmu}")
        _ellenoriz(self.allapot in FUTAR_ALLAPOTOK, f"Érvénytelen állapot: {self.allapot}")
        _ellenoriz(self.hatosugar_km > 0, "A hatósugár pozitív kell legyen.")
        _ellenoriz(self.jarmu != "dron" or self.ember == 0,
                   "Dróngyalogos futár nem lehet 'ember'.")

    # --- üzleti logika ---
    def elerheto(self) -> bool:
        return self.allapot == "elerheto"

    def kiszallithat(self, km: int) -> bool:
        """Elérhető és a hatósugarán belül van a cél."""
        return self.elerheto() and km <= self.hatosugar_km

    @classmethod
    def sorbol(cls, sor) -> Futar:
        return cls(id=sor["id"], nev=sor["nev"], telszam=sor["telszam"],
                   jarmu=sor["jarmu"], ember=sor["ember"], allapot=sor["allapot"],
                   hatosugar_km=sor["hatosugar_km"])


@dataclass
class FutarPozicio:
    futar_id: int      # az SQL-ben: futarID
    gps_x: float       # az SQL-ben REAL
    gps_y: float       # az SQL-ben INTEGER (érdemes REAL-ra egységesíteni)
    cim: str
    id: int | None = None

    @classmethod
    def sorbol(cls, sor) -> FutarPozicio:
        return cls(id=sor["id"], futar_id=sor["futarID"], gps_x=sor["gps_x"],
                   gps_y=sor["gps_y"], cim=sor["cim"])


@dataclass
class Termek:
    nev: str
    fogas: str
    ar: int
    tipus: str = "etel"
    leiras: str | None = None
    elkeszitesi_ido: int | None = None
    prioritas: int = 0
    allergenek: list[Allergen] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(self.tipus in TERMEK_TIPUSOK, f"Érvénytelen típus: {self.tipus}")
        _ellenoriz(self.ar >= 0, "Az ár nem lehet negatív.")

    @classmethod
    def sorbol(cls, sor, allergenek: list[Allergen] | None = None) -> Termek:
        return cls(id=sor["id"], tipus=sor["tipus"], nev=sor["nev"], fogas=sor["fogas"],
                   leiras=sor["leiras"], ar=sor["ar"],
                   elkeszitesi_ido=sor["elkeszitesi_ido"], prioritas=sor["prioritas"],
                   allergenek=allergenek or [])


@dataclass
class RendelesTetel:
    termek: Termek
    db: int = 1

    def __post_init__(self):
        _ellenoriz(self.db >= 1, "A darabszám legalább 1.")

    def osszeg(self) -> int:
        return self.termek.ar * self.db


@dataclass
class Rendeles:
    felhasznalo_id: int
    futar_id: int
    cim: str
    fizetesi_mod: str
    szamla: int
    km: int
    ertekeles: int | None = None  # az SQL-ben NOT NULL; itt None = még nincs értékelve
    prioritas: int = 0
    jatt: int | None = None
    statusz: str = "új"
    tetelek: list[RendelesTetel] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(self.fizetesi_mod in FIZETESI_MODOK, f"Érvénytelen fizetési mód: {self.fizetesi_mod}")
        _ellenoriz(self.prioritas in (0, 1), "A prioritás 0 vagy 1.")
        _ellenoriz(self.szamla in (0, 1), "A számla 0 vagy 1.")
        _ellenoriz(self.km > 0, "A km pozitív kell legyen.")
        _ellenoriz(self.ertekeles is None or self.ertekeles in (1, 2, 3, 4, 5),
                   "Az értékelés 1 és 5 közötti.")
        _ellenoriz(self.jatt is None or (self.jatt > 0 and self.fizetesi_mod == "kartya"),
                   "Borravaló (jatt) csak kártyás fizetésnél, pozitív összeggel adható.")

    # --- üzleti logika ---
    def tetel_hozzaad(self, termek: Termek, db: int = 1) -> None:
        for t in self.tetelek:           # ugyanaz a termék: darabszám növelése
            if t.termek.id is not None and t.termek.id == termek.id:
                t.db += db
                return
        self.tetelek.append(RendelesTetel(termek, db))

    def vegosszeg(self) -> int:
        return sum(t.osszeg() for t in self.tetelek)

    def allergenek(self) -> set[str]:
        return {a.nev for t in self.tetelek for a in t.termek.allergenek}
