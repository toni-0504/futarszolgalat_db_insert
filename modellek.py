"""Modellréteg a futárszolgálathoz.

Az osztályok az adatbázis tábláit képezik le, validálják az adatot (ugyanazok a
szabályok, mint az SQL CHECK-ek), és tartalmazzák az üzleti logikát.
Adatbázisba írás itt NINCS. Az id None, amíg az objektumot valaki el nem mentette.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import bcrypt

JARMUVEK = ("auto", "bicikli", "motor")
FUTAR_ALLAPOTOK = ("elerheto", "uton", "szunet")
TERMEK_TIPUSOK = ("etel", "ital")
FIZETESI_MODOK = ("keszpenz", "kartya")

# A rendeles.statusz CHECK értékei. A folyamat: új -> elfogadva (futár felveszi)
# -> készül (konyha) -> úton (futár átveszi) -> kiszállítva; új -> lemondva.
# A 'kosar' állapotot az adatbázis engedi, az API nem hoz létre ilyet.
RENDELES_STATUSZOK = ("kosar", "új", "elfogadva", "készül", "úton", "kiszállítva", "lemondva")
AKTIV_STATUSZOK = ("elfogadva", "készül", "úton")      # a futárnál lévő rendelések
FUTAR_NELKULI_STATUSZOK = ("kosar", "új", "lemondva")  # ck_rendeles_futar_kotelezo


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

    def __post_init__(self):
        _ellenoriz(bool(self.nev.strip()), "Az allergén neve nem lehet üres.")

    @classmethod
    def sorbol(cls, sor) -> Allergen:
        """sor: sqlite3.Row vagy dict a 'allergen' táblából."""
        return cls(kod=sor["kod"], nev=sor["nev"])


@dataclass
class Fogas:
    kod: str
    tipus: str

    @classmethod
    def sorbol(cls, sor) -> Fogas:
        return cls(kod=sor["kod"], tipus=sor["tipus"])


_EMAIL_MINTA = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# +36 vagy 06 kezdet, utána csak számjegyek (üzleti szabály; az SQL 9-16 karaktert enged)
_TELSZAM_MINTA = re.compile(r"^(\+36|06)[0-9]{8,9}$")
_ADOSZAM_MINTA = re.compile(r"^\d{8}-\d-\d{2}$")
MIN_JELSZO_HOSSZ = 8


def jelszo_hash(jelszo: str) -> str:
    """bcrypt hash '$2y$' előtaggal, hogy a Laravel (PHP) is ellenőrizni tudja."""
    h = bcrypt.hashpw(jelszo.encode(), bcrypt.gensalt(12)).decode()
    return "$2y$" + h[4:]


def _telszam_ellenoriz(telszam: str) -> None:
    _ellenoriz(bool(_TELSZAM_MINTA.match(telszam)),
               "A telefonszám +36 vagy 06 kezdetű, utána csak számjegyek.")


@dataclass
class Felhasznalo:
    nev: str
    cim: str
    telszam: str
    email: str
    jelszo_hash: str = field(repr=False)   # az SQL-ben: password (bcrypt hash)
    admin: bool = False                    # az SQL-ben: isAdmin
    aktiv: bool = True
    id: int | None = None

    def __post_init__(self):
        for mezo in ("nev", "cim", "telszam"):
            _ellenoriz(bool(getattr(self, mezo).strip()), f"A(z) {mezo} nem lehet üres.")
        self.email = self.email.strip().lower()
        _ellenoriz(bool(_EMAIL_MINTA.match(self.email)), f"Érvénytelen email: {self.email}")

    @classmethod
    def regisztral(cls, nev: str, cim: str, telszam: str, email: str,
                   jelszo: str, admin: bool = False) -> Felhasznalo:
        """Új felhasználó; a jelszót csak hashelve tároljuk."""
        _telszam_ellenoriz(telszam)
        _ellenoriz(len(jelszo) >= MIN_JELSZO_HOSSZ,
                   f"A jelszó legalább {MIN_JELSZO_HOSSZ} karakter legyen.")
        return cls(nev, cim, telszam, email, jelszo_hash(jelszo), admin)

    def jelszo_beallit(self, jelszo: str) -> None:
        _ellenoriz(len(jelszo) >= MIN_JELSZO_HOSSZ,
                   f"A jelszó legalább {MIN_JELSZO_HOSSZ} karakter legyen.")
        self.jelszo_hash = jelszo_hash(jelszo)

    def jelszo_helyes(self, jelszo: str) -> bool:
        try:
            return bcrypt.checkpw(jelszo.encode(), self.jelszo_hash.encode())
        except ValueError:  # nem bcrypt hash van az adatbázisban
            return False

    @classmethod
    def sorbol(cls, sor) -> Felhasznalo:
        return cls(id=sor["id"], nev=sor["nev"], cim=sor["cim"], telszam=sor["telszam"],
                   email=sor["email"], jelszo_hash=sor["password"],
                   admin=bool(sor["isAdmin"]), aktiv=bool(sor["aktiv"]))


@dataclass
class Futar:
    nev: str
    telszam: str
    jarmu: str
    hatosugar_km: int
    allapot: str = "elerheto"
    aktiv: bool = True
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(bool(self.nev.strip()), "A név nem lehet üres.")
        _telszam_ellenoriz(self.telszam)
        _ellenoriz(self.jarmu in JARMUVEK, f"Érvénytelen jármű: {self.jarmu}")
        _ellenoriz(self.allapot in FUTAR_ALLAPOTOK, f"Érvénytelen állapot: {self.allapot}")
        _ellenoriz(self.hatosugar_km > 0, "A hatósugár pozitív kell legyen.")

    # --- üzleti logika ---
    def elerheto(self) -> bool:
        return self.aktiv and self.allapot == "elerheto"

    def kiszallithat(self, km: int) -> bool:
        """Elérhető és a hatósugarán belül van a cél."""
        return self.elerheto() and km <= self.hatosugar_km

    @classmethod
    def sorbol(cls, sor) -> Futar:
        return cls(id=sor["id"], nev=sor["nev"], telszam=sor["telszam"],
                   jarmu=sor["jarmu"], allapot=sor["allapot"],
                   hatosugar_km=sor["hatosugar_km"], aktiv=bool(sor["aktiv"]))


@dataclass
class FutarPozicio:
    """Futáronként egy sor (futarID UNIQUE): az aktuális pozíció."""
    futar_id: int      # az SQL-ben: futarID
    gps_x: float       # szélesség, fokban
    gps_y: float       # hosszúság, fokban
    cim: str
    frissitve: str | None = None
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(-90 <= self.gps_x <= 90, "A gps_x (szélesség) -90 és 90 közötti fok.")
        _ellenoriz(-180 <= self.gps_y <= 180, "A gps_y (hosszúság) -180 és 180 közötti fok.")
        _ellenoriz(bool(self.cim.strip()), "A cím nem lehet üres.")

    @classmethod
    def sorbol(cls, sor) -> FutarPozicio:
        return cls(id=sor["id"], futar_id=sor["futarID"], gps_x=sor["gps_x"],
                   gps_y=sor["gps_y"], cim=sor["cim"], frissitve=sor["frissitve"])


@dataclass
class Termek:
    nev: str
    fogas: str
    ar: int
    tipus: str = "etel"
    leiras: str | None = None
    elkeszitesi_ido: int | None = None
    prioritas: int = 0
    aktiv: bool = True
    allergen_ellenorizve: bool = False
    allergenek: list[Allergen] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(bool(self.nev.strip()), "A név nem lehet üres.")
        _ellenoriz(self.tipus in TERMEK_TIPUSOK, f"Érvénytelen típus: {self.tipus}")
        _ellenoriz(self.ar >= 0, "Az ár nem lehet negatív.")
        _ellenoriz(self.prioritas >= 0, "A prioritás nem lehet negatív.")
        if self.tipus == "etel":
            _ellenoriz(self.elkeszitesi_ido is not None and self.elkeszitesi_ido > 0,
                       "Ételnél az elkészítési idő kötelező és pozitív.")
        else:
            _ellenoriz(self.elkeszitesi_ido is None or self.elkeszitesi_ido >= 0,
                       "Az elkészítési idő nem lehet negatív.")

    @classmethod
    def sorbol(cls, sor, allergenek: list[Allergen] | None = None) -> Termek:
        return cls(id=sor["id"], tipus=sor["tipus"], nev=sor["nev"], fogas=sor["fogas"],
                   leiras=sor["leiras"], ar=sor["ar"],
                   elkeszitesi_ido=sor["elkeszitesi_ido"], prioritas=sor["prioritas"],
                   aktiv=bool(sor["aktiv"]),
                   allergen_ellenorizve=bool(sor["allergen_ellenorizve"]),
                   allergenek=allergenek or [])


@dataclass
class RendelesTetel:
    termek: Termek
    db: int = 1
    egysegar: int | None = None   # a rendeléskori ár; None = a termék mostani ára

    def __post_init__(self):
        _ellenoriz(self.db >= 1, "A darabszám legalább 1.")
        if self.egysegar is None:
            self.egysegar = self.termek.ar

    def osszeg(self) -> int:
        return self.egysegar * self.db


@dataclass
class SzamlazasiAdat:
    nev: str
    cim: str
    adoszam: str | None = None

    def __post_init__(self):
        _ellenoriz(bool(self.nev.strip()), "A számlázási név nem lehet üres.")
        _ellenoriz(bool(self.cim.strip()), "A számlázási cím nem lehet üres.")
        _ellenoriz(self.adoszam is None or bool(_ADOSZAM_MINTA.match(self.adoszam)),
                   "Az adószám formátuma 12345678-1-12.")


@dataclass
class Rendeles:
    felhasznalo_id: int
    cim: str
    fizetesi_mod: str
    szamla: int
    km: int | None
    futar_id: int | None = None
    prioritas: int = 0
    jatt: int | None = None
    szallitasi_dij: int = 0
    statusz: str = "új"
    ertekeles: int | None = None
    letrehozva: str | None = None
    kiszallitva_ido: str | None = None
    tetelek: list[RendelesTetel] = field(default_factory=list)
    szamlazasi_adat: SzamlazasiAdat | None = None
    id: int | None = None

    def __post_init__(self):
        _ellenoriz(bool(self.cim.strip()), "A szállítási cím nem lehet üres.")
        _ellenoriz(self.fizetesi_mod in FIZETESI_MODOK, f"Érvénytelen fizetési mód: {self.fizetesi_mod}")
        _ellenoriz(self.prioritas in (0, 1), "A prioritás 0 vagy 1.")
        _ellenoriz(self.szamla in (0, 1), "A számla 0 vagy 1.")
        _ellenoriz(self.statusz in RENDELES_STATUSZOK, f"Érvénytelen státusz: {self.statusz}")
        _ellenoriz(self.km is not None or self.statusz == "kosar", "A km kötelező.")
        _ellenoriz(self.km is None or self.km > 0, "A km pozitív kell legyen.")
        _ellenoriz(self.szallitasi_dij >= 0, "A szállítási díj nem lehet negatív.")
        _ellenoriz(self.futar_id is not None or self.statusz in FUTAR_NELKULI_STATUSZOK,
                   "Ebben a státuszban a rendelésnek futár kell.")
        _ellenoriz(self.ertekeles is None or (self.ertekeles in (1, 2, 3, 4, 5)
                                              and self.statusz == "kiszállítva"),
                   "Értékelni csak kiszállított rendelést lehet, 1 és 5 között.")
        _ellenoriz(self.jatt is None or (self.jatt > 0 and self.fizetesi_mod == "kartya"
                                         and self.statusz == "kiszállítva"),
                   "Jatt csak kiszállított, kártyás rendeléshez adható, pozitív összeggel.")

    # --- üzleti logika ---
    def tetel_hozzaad(self, termek: Termek, db: int = 1) -> None:
        for t in self.tetelek:           # ugyanaz a termék: darabszám növelése
            if t.termek.id is not None and t.termek.id == termek.id:
                t.db += db
                return
        self.tetelek.append(RendelesTetel(termek, db))

    def termek_osszeg(self) -> int:
        return sum(t.osszeg() for t in self.tetelek)

    def vegosszeg(self) -> int:
        """Termékek + szállítási díj + jatt (mint a v_rendeles_osszeg nézetben)."""
        return self.termek_osszeg() + self.szallitasi_dij + (self.jatt or 0)

    def allergenek(self) -> set[str]:
        return {a.nev for t in self.tetelek for a in t.termek.allergenek}
