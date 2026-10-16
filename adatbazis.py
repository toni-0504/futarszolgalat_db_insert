"""SQLite mentés/betöltés és üzleti folyamatok a modellek (modellek.py) használatával.

A függvények modellobjektumot fogadnak és adnak vissza. A mentők beállítják az
objektum id-ját is, és több táblát érintő műveletek egy tranzakcióban futnak.
Az állapotváltások feltételes UPDATE-tel mennek (WHERE ... AND statusz = ...), így
két egyszerre érkező kérés közül csak az egyik tud sikerülni.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

try:
    from .modellek import (AKTIV_STATUSZOK, Allergen, Felhasznalo, Fogas, Futar,
                           FutarPozicio, Rendeles, RendelesTetel, SzamlazasiAdat, Termek,
                           FUTAR_ALLAPOTOK, ValidacioHiba)
except ImportError:
    from modellek import (AKTIV_STATUSZOK, Allergen, Felhasznalo, Fogas, Futar,
                          FutarPozicio, Rendeles, RendelesTetel, SzamlazasiAdat, Termek,
                          FUTAR_ALLAPOTOK, ValidacioHiba)

# Alapból a script mappájában lévő adatbázis; a FUTARSZOLGALAT_DB környezeti
# változóval más fájl adható meg (pl. teszteknél vagy tartós tárhelyen).
ALAP_DB_PATH = Path(__file__).resolve().parent / "futarszolgalat.db"

_AKTIV_IN = "('" + "', '".join(AKTIV_STATUSZOK) + "')"


class NemTalalhato(LookupError):
    """A keresett rekord nem létezik."""


class UzletiHiba(Exception):
    """A kérés ütközik egy üzleti szabállyal (pl. rossz státuszban lévő rendelés)."""


class JogosultsagHiba(Exception):
    """A kérő nem jogosult a műveletre (pl. nem a saját rendelése)."""


def db_path() -> Path:
    return Path(os.environ.get("FUTARSZOLGALAT_DB") or ALAP_DB_PATH)


# ---------------------------------------------------------------------------
# Kapcsolat
# ---------------------------------------------------------------------------
@contextmanager
def kapcsolat():
    """Siker esetén commit, hiba esetén rollback, a végén mindig zár."""
    conn = sqlite3.connect(f"file:{db_path().as_posix()}?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite-ban alapból ki van kapcsolva
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _letezik(conn: sqlite3.Connection, tabla: str, rekord_id, uzenet: str,
             kulcs: str = "id") -> sqlite3.Row:
    sor = conn.execute(f"SELECT * FROM {tabla} WHERE {kulcs} = ?", (rekord_id,)).fetchone()
    if sor is None:
        raise NemTalalhato(uzenet)
    return sor


# ---------------------------------------------------------------------------
# Felhasználó (törlés helyett inaktiválás: a rendelések ON DELETE RESTRICT-tel hivatkoznak rá)
# ---------------------------------------------------------------------------
def felhasznalo_letrehoz(f: Felhasznalo) -> int:
    """Elmenti a felhasználót, beállítja f.id-t, és visszaadja az új id-t."""
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO felhasznalo (nev, cim, telszam, email, password, isAdmin, aktiv)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (f.nev, f.cim, f.telszam, f.email, f.jelszo_hash, int(f.admin), int(f.aktiv)),
        )
        f.id = cur.lastrowid
        return f.id


def felhasznalo_lekerdez(felhasznalo_id: int) -> Felhasznalo | None:
    with kapcsolat() as conn:
        sor = conn.execute(
            "SELECT * FROM felhasznalo WHERE id = ?", (felhasznalo_id,)
        ).fetchone()
        return Felhasznalo.sorbol(sor) if sor else None


def felhasznalo_modosit(f: Felhasznalo) -> bool:
    """A már mentett (id-val rendelkező) felhasználó adatait frissíti."""
    if f.id is None:
        raise ValueError("A felhasználó még nincs elmentve (nincs id).")
    with kapcsolat() as conn:
        cur = conn.execute(
            """UPDATE felhasznalo
               SET nev = ?, cim = ?, telszam = ?, email = ?, password = ?, isAdmin = ?, aktiv = ?
               WHERE id = ?""",
            (f.nev, f.cim, f.telszam, f.email, f.jelszo_hash, int(f.admin), int(f.aktiv), f.id),
        )
        return cur.rowcount > 0


def felhasznalo_lekerdez_emailre(email: str) -> Felhasznalo | None:
    with kapcsolat() as conn:
        sor = conn.execute(
            "SELECT * FROM felhasznalo WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return Felhasznalo.sorbol(sor) if sor else None


def bejelentkezes(email: str, jelszo: str) -> Felhasznalo | None:
    """A felhasználót adja vissza, ha aktív, és az email és a jelszó helyes, különben None.
    Szándékosan nem árulja el, hogy az email vagy a jelszó volt-e rossz."""
    f = felhasznalo_lekerdez_emailre(email)
    return f if f and f.aktiv and f.jelszo_helyes(jelszo) else None


def felhasznalo_inaktival(felhasznalo_id: int) -> bool:
    """A rendelési előzmények megmaradnak; az inaktív felhasználó nem tud belépni."""
    with kapcsolat() as conn:
        cur = conn.execute("UPDATE felhasznalo SET aktiv = 0 WHERE id = ?", (felhasznalo_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Futár (törlés helyett inaktiválás)
# ---------------------------------------------------------------------------
def futar_letrehoz(f: Futar) -> int:
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO futar (nev, telszam, jarmu, allapot, hatosugar_km, aktiv)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f.nev, f.telszam, f.jarmu, f.allapot, f.hatosugar_km, int(f.aktiv)),
        )
        f.id = cur.lastrowid
        return f.id


def futar_lekerdez(futar_id: int) -> Futar | None:
    with kapcsolat() as conn:
        sor = conn.execute("SELECT * FROM futar WHERE id = ?", (futar_id,)).fetchone()
        return Futar.sorbol(sor) if sor else None


def futar_lekerdez_bejelentkezeshez(nev: str, telszam: str) -> Futar | None:
    """Futár azonosítása névvel és telefonszámmal (csak aktív futár)."""
    with kapcsolat() as conn:
        sor = conn.execute(
            "SELECT * FROM futar WHERE nev = ? AND telszam = ? AND aktiv = 1", (nev, telszam)
        ).fetchone()
        return Futar.sorbol(sor) if sor else None


def futar_modosit(f: Futar) -> bool:
    """Az adatokat frissíti; az állapotot nem (arra a futar_allapot_valt való)."""
    if f.id is None:
        raise ValueError("A futár még nincs elmentve (nincs id).")
    with kapcsolat() as conn:
        cur = conn.execute(
            """UPDATE futar SET nev = ?, telszam = ?, jarmu = ?, hatosugar_km = ?, aktiv = ?
               WHERE id = ?""",
            (f.nev, f.telszam, f.jarmu, f.hatosugar_km, int(f.aktiv), f.id),
        )
        return cur.rowcount > 0


def _aktiv_rendeles_id(conn: sqlite3.Connection, futar_id: int) -> int | None:
    sor = conn.execute(
        f"SELECT id FROM rendeles WHERE futar_id = ? AND statusz IN {_AKTIV_IN}", (futar_id,)
    ).fetchone()
    return sor["id"] if sor else None


def futar_inaktival(futar_id: int) -> None:
    """Aktív rendeléssel rendelkező futár nem inaktiválható."""
    with kapcsolat() as conn:
        _letezik(conn, "futar", futar_id, "Futár nem található")
        cur = conn.execute(
            f"""UPDATE futar SET aktiv = 0 WHERE id = ? AND NOT EXISTS (
                    SELECT 1 FROM rendeles WHERE futar_id = futar.id AND statusz IN {_AKTIV_IN})""",
            (futar_id,),
        )
        if cur.rowcount == 0:
            raise UzletiHiba("Aktív rendeléssel rendelkező futár nem inaktiválható.")


def futar_allapot_valt(futar_id: int, allapot: str) -> None:
    """Kézi váltás csak elerheto <-> szunet lehet. Az 'uton' állapotot a rendelés
    felvétele állítja be, és a kiszállítás állítja vissza; úton lévő futár nem mehet szünetre."""
    if allapot not in FUTAR_ALLAPOTOK:
        raise ValidacioHiba(
            f"Érvénytelen futárállapot: {allapot}. "
            f"Lehetséges értékek: {', '.join(FUTAR_ALLAPOTOK)}."
        )
    if allapot == "uton":
        raise UzletiHiba("Az 'uton' állapot csak rendelés felvételével állítható be.")
    honnan = "elerheto" if allapot == "szunet" else "szunet"
    with kapcsolat() as conn:
        _letezik(conn, "futar", futar_id, "Futár nem található")
        cur = conn.execute(
            f"""UPDATE futar SET allapot = ? WHERE id = ? AND allapot = ? AND NOT EXISTS (
                    SELECT 1 FROM rendeles WHERE futar_id = futar.id AND statusz IN {_AKTIV_IN})""",
            (allapot, futar_id, honnan),
        )
        if cur.rowcount == 0:
            raise UzletiHiba(f"Ez az állapotváltás nem engedélyezett (csak {honnan} -> {allapot}, "
                             "aktív rendelés nélkül).")


def elerheto_futarok(jarmu: str | None = None) -> list[Futar]:
    """Aktív, elérhető állapotú, aktív rendelés nélküli futárok."""
    sql = f"""SELECT * FROM futar WHERE aktiv = 1 AND allapot = 'elerheto'
              AND NOT EXISTS (SELECT 1 FROM rendeles
                              WHERE futar_id = futar.id AND statusz IN {_AKTIV_IN})"""
    param: tuple = ()
    if jarmu:
        sql += " AND jarmu = ?"
        param = (jarmu,)
    with kapcsolat() as conn:
        return [Futar.sorbol(s) for s in conn.execute(sql + " ORDER BY id", param)]


def szallitasra_alkalmas_futarok(km: int) -> list[Futar]:
    """Az elérhető, a megadott távolságot vállalni képes futárok."""
    if km <= 0:
        raise ValidacioHiba("A távolságnak pozitívnak kell lennie.")
    return [futar for futar in elerheto_futarok() if futar.kiszallithat(km)]


# ---------------------------------------------------------------------------
# Futár pozíciója: futáronként egy sor (futarID UNIQUE), rögzítéskor felülíródik
# ---------------------------------------------------------------------------
def futar_pozicio_rogzit(p: FutarPozicio) -> FutarPozicio:
    """Csak úton lévő, aktív futár rögzíthet pozíciót."""
    with kapcsolat() as conn:
        futar = _letezik(conn, "futar", p.futar_id, "Futár nem található")
        if not futar["aktiv"] or futar["allapot"] != "uton":
            raise UzletiHiba("A pozíciót csak úton lévő, aktív futár frissítheti.")
        conn.execute(
            """INSERT INTO futar_pozicio (futarID, gps_x, gps_y, cim, frissitve)
               VALUES (?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
               ON CONFLICT (futarID) DO UPDATE SET
                   gps_x = excluded.gps_x, gps_y = excluded.gps_y,
                   cim = excluded.cim, frissitve = excluded.frissitve""",
            (p.futar_id, p.gps_x, p.gps_y, p.cim),
        )
        return FutarPozicio.sorbol(_letezik(conn, "futar_pozicio", p.futar_id,
                                            "Pozíció nem található", kulcs="futarID"))


def futar_pozicio_lekerdez(futar_id: int) -> FutarPozicio | None:
    """A futár aktuális (utoljára rögzített) pozíciója."""
    with kapcsolat() as conn:
        sor = conn.execute(
            "SELECT * FROM futar_pozicio WHERE futarID = ?", (futar_id,)
        ).fetchone()
        return FutarPozicio.sorbol(sor) if sor else None


# ---------------------------------------------------------------------------
# Fogás és allergén
# ---------------------------------------------------------------------------
def fogasok_lekerdez() -> list[Fogas]:
    with kapcsolat() as conn:
        return [Fogas.sorbol(s) for s in conn.execute("SELECT * FROM fogas ORDER BY tipus, kod")]


def allergenek_lekerdez() -> list[Allergen]:
    with kapcsolat() as conn:
        return [Allergen.sorbol(s) for s in conn.execute("SELECT * FROM allergen ORDER BY kod")]


def _allergen_nev_szabad(conn: sqlite3.Connection, nev: str, sajat_kod: int | None = None) -> None:
    """A név kis- és nagybetűtől függetlenül egyedi. A COLLATE NOCASE csak az ASCII
    betűket hasonlítja így (Á és á különbözne), ezért itt Unicode szerint is ellenőrizzük."""
    keresett = nev.strip().casefold()
    for sor in conn.execute("SELECT kod, nev FROM allergen"):
        if sor["kod"] != sajat_kod and sor["nev"].casefold() == keresett:
            raise UzletiHiba(f"Már létezik ilyen nevű allergén: {sor['nev']}")


def allergen_letrehoz(a: Allergen) -> int:
    with kapcsolat() as conn:
        _allergen_nev_szabad(conn, a.nev)
        cur = conn.execute("INSERT INTO allergen (nev) VALUES (?)", (a.nev.strip(),))
        a.kod = cur.lastrowid
        return a.kod


def allergen_modosit(a: Allergen) -> bool:
    with kapcsolat() as conn:
        _allergen_nev_szabad(conn, a.nev, a.kod)
        cur = conn.execute("UPDATE allergen SET nev = ? WHERE kod = ?", (a.nev.strip(), a.kod))
        return cur.rowcount > 0


def allergen_torol(kod: int) -> None:
    """Használatban lévő allergén nem törölhető (ON DELETE RESTRICT)."""
    with kapcsolat() as conn:
        _letezik(conn, "allergen", kod, "Allergén nem található", kulcs="kod")
        if conn.execute("SELECT 1 FROM termek_allergen WHERE allergen_kod = ?", (kod,)).fetchone():
            raise UzletiHiba("Használatban lévő allergén nem törölhető.")
        conn.execute("DELETE FROM allergen WHERE kod = ?", (kod,))


# ---------------------------------------------------------------------------
# Termék (+ allergének a kapcsolótáblában)
# ---------------------------------------------------------------------------
def _termek_ellenoriz(conn: sqlite3.Connection, t: Termek) -> None:
    """A (fogas, tipus) párnak léteznie kell a fogas táblában (fk_termek_fogas),
    és minden allergénkódnak az allergen táblában."""
    if not conn.execute("SELECT 1 FROM fogas WHERE kod = ? AND tipus = ?",
                        (t.fogas, t.tipus)).fetchone():
        raise ValidacioHiba(f"Nincs '{t.fogas}' fogás '{t.tipus}' típushoz.")
    kodok = {a.kod for a in t.allergenek}
    if kodok:
        meglevo = {s["kod"] for s in conn.execute(
            f"SELECT kod FROM allergen WHERE kod IN ({', '.join('?' * len(kodok))})", list(kodok))}
        hianyzo = sorted(kodok - meglevo)
        if hianyzo:
            raise NemTalalhato(f"Nem található allergénkód: {', '.join(map(str, hianyzo))}")


def termek_letrehoz(t: Termek) -> int:
    """A terméket és az allergénkapcsolatait egy tranzakcióban menti."""
    with kapcsolat() as conn:
        _termek_ellenoriz(conn, t)
        cur = conn.execute(
            """INSERT INTO termek (tipus, nev, fogas, leiras, ar, elkeszitesi_ido, prioritas,
                                   aktiv, allergen_ellenorizve)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t.tipus, t.nev, t.fogas, t.leiras, t.ar, t.elkeszitesi_ido, t.prioritas,
             int(t.aktiv), int(t.allergen_ellenorizve)),
        )
        t.id = cur.lastrowid
        conn.executemany(
            "INSERT INTO termek_allergen (termek_id, allergen_kod) VALUES (?, ?)",
            [(t.id, a.kod) for a in t.allergenek],
        )
        return t.id


def termek_modosit(t: Termek) -> bool:
    """Az adatokat és az allergénlistát is lecseréli, egy tranzakcióban."""
    if t.id is None:
        raise ValueError("A termék még nincs elmentve (nincs id).")
    with kapcsolat() as conn:
        _termek_ellenoriz(conn, t)
        cur = conn.execute(
            """UPDATE termek SET tipus = ?, nev = ?, fogas = ?, leiras = ?, ar = ?,
                   elkeszitesi_ido = ?, prioritas = ?, aktiv = ?, allergen_ellenorizve = ?
               WHERE id = ?""",
            (t.tipus, t.nev, t.fogas, t.leiras, t.ar, t.elkeszitesi_ido, t.prioritas,
             int(t.aktiv), int(t.allergen_ellenorizve), t.id),
        )
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM termek_allergen WHERE termek_id = ?", (t.id,))
        conn.executemany(
            "INSERT INTO termek_allergen (termek_id, allergen_kod) VALUES (?, ?)",
            [(t.id, a.kod) for a in t.allergenek],
        )
        return True


def termek_torol(termek_id: int) -> None:
    """Rendelésben már szerepelt termék nem törölhető, csak inaktiválható (aktiv = 0)."""
    with kapcsolat() as conn:
        _letezik(conn, "termek", termek_id, "Termék nem található")
        if conn.execute("SELECT 1 FROM rendeles_tetel WHERE termek_id = ?", (termek_id,)).fetchone():
            raise UzletiHiba("Rendelésben már szerepelt termék nem törölhető, csak inaktiválható.")
        conn.execute("DELETE FROM termek WHERE id = ?", (termek_id,))


def termek_lekerdez(termek_id: int) -> Termek | None:
    with kapcsolat() as conn:
        return _termek_betolt(conn, termek_id)


def _termek_betolt(conn: sqlite3.Connection, termek_id: int) -> Termek | None:
    """Belső segéd: a terméket az allergénjeivel együtt tölti be."""
    sor = conn.execute("SELECT * FROM termek WHERE id = ?", (termek_id,)).fetchone()
    if not sor:
        return None
    allergenek = [Allergen.sorbol(a) for a in conn.execute(
        """SELECT a.kod, a.nev FROM allergen a
           JOIN termek_allergen ta ON ta.allergen_kod = a.kod
           WHERE ta.termek_id = ? ORDER BY a.kod""", (termek_id,))]
    return Termek.sorbol(sor, allergenek)


# ---------------------------------------------------------------------------
# Rendelés: leadás, tételek, lemondás, értékelés, jatt
# ---------------------------------------------------------------------------
def rendeles_letrehoz(felhasznalo_id: int, *, km: int, fizetesi_mod: str,
                      tetelek: list[tuple[int, int]], cim: str | None = None,
                      prioritas: int = 0, szamla: int = 0,
                      szamlazasi_adat: SzamlazasiAdat | None = None) -> Rendeles:
    """Új rendelés 'új' státusszal, futár nélkül; a fejléc, a tételek (rendeléskori
    egységárral) és a számlázási adat vagy mind elmentődik, vagy egyik sem.
    A cím és a számlázási adat alapból a felhasználóé."""
    if not tetelek:
        raise ValidacioHiba("Legalább egy tétel szükséges a rendeléshez.")
    if szamlazasi_adat is not None and not szamla:
        raise ValidacioHiba("Számlázási adat csak számlakéréssel adható meg.")
    with kapcsolat() as conn:
        felh = _letezik(conn, "felhasznalo", felhasznalo_id, "Felhasználó nem található")
        if not felh["aktiv"]:
            raise UzletiHiba("Inaktív felhasználó nem rendelhet.")
        rendeles = Rendeles(felhasznalo_id=felhasznalo_id, cim=cim or felh["cim"],
                            fizetesi_mod=fizetesi_mod, szamla=szamla, km=km,
                            prioritas=prioritas)
        for termek_id, db in tetelek:
            termek = _termek_betolt(conn, termek_id)
            if termek is None or not termek.aktiv:
                raise UzletiHiba(f"Inaktív vagy nem létező termék nem rendelhető: {termek_id}")
            rendeles.tetel_hozzaad(termek, db)
        cur = conn.execute(
            """INSERT INTO rendeles (felhasznalo_id, futar_id, cim, prioritas, fizetesi_mod,
                                     szamla, km, statusz)
               VALUES (?, NULL, ?, ?, ?, ?, ?, 'új')""",
            (felhasznalo_id, rendeles.cim, prioritas, fizetesi_mod, szamla, km),
        )
        rendeles.id = cur.lastrowid
        conn.executemany(
            "INSERT INTO rendeles_tetel (rendeles_id, termek_id, db, egysegar) VALUES (?, ?, ?, ?)",
            [(rendeles.id, t.termek.id, t.db, t.egysegar) for t in rendeles.tetelek],
        )
        if szamla:
            adat = szamlazasi_adat or SzamlazasiAdat(felh["nev"], felh["cim"])
            conn.execute(
                "INSERT INTO szamlazasi_adat (rendeles_id, nev, cim, adoszam) VALUES (?, ?, ?, ?)",
                (rendeles.id, adat.nev, adat.cim, adat.adoszam),
            )
        return _rendeles_betolt(conn, _letezik(conn, "rendeles", rendeles.id, "Rendelés nem található"))


def rendeles_lekerdez(rendeles_id: int) -> Rendeles | None:
    """A rendelést a tételeivel és azok termékeivel együtt tölti be."""
    with kapcsolat() as conn:
        sor = conn.execute(
            "SELECT * FROM rendeles WHERE id = ?", (rendeles_id,)
        ).fetchone()
        return _rendeles_betolt(conn, sor) if sor else None


def _rendeles_betolt(conn: sqlite3.Connection, sor: sqlite3.Row) -> Rendeles:
    """Belső segéd: egy rendelés-sorból teljes Rendeles objektumot épít (tételekkel)."""
    tetelek = [
        RendelesTetel(_termek_betolt(conn, ts["termek_id"]), ts["db"], ts["egysegar"])
        for ts in conn.execute(
            "SELECT termek_id, db, egysegar FROM rendeles_tetel WHERE rendeles_id = ? "
            "ORDER BY termek_id", (sor["id"],))
    ]
    szamla_sor = conn.execute(
        "SELECT * FROM szamlazasi_adat WHERE rendeles_id = ?", (sor["id"],)
    ).fetchone()
    return Rendeles(
        id=sor["id"], felhasznalo_id=sor["felhasznalo_id"],
        futar_id=sor["futar_id"], cim=sor["cim"], prioritas=sor["prioritas"],
        fizetesi_mod=sor["fizetesi_mod"], jatt=sor["jatt"], szamla=sor["szamla"],
        km=sor["km"], szallitasi_dij=sor["szallitasi_dij"], statusz=sor["statusz"],
        ertekeles=sor["ertekeles"], letrehozva=sor["letrehozva"],
        kiszallitva_ido=sor["kiszallitva_ido"], tetelek=tetelek,
        szamlazasi_adat=SzamlazasiAdat(szamla_sor["nev"], szamla_sor["cim"], szamla_sor["adoszam"])
        if szamla_sor else None,
    )


def _sajat_rendeles(conn: sqlite3.Connection, rendeles_id: int, felhasznalo_id: int) -> sqlite3.Row:
    """A rendelés sora, ha a kérő aktív felhasználó és ő a megrendelő."""
    sor = _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található")
    if sor["felhasznalo_id"] != felhasznalo_id:
        raise JogosultsagHiba("Csak a megrendelő módosíthatja a rendelést.")
    if not _letezik(conn, "felhasznalo", felhasznalo_id, "Felhasználó nem található")["aktiv"]:
        raise JogosultsagHiba("Inaktív felhasználó nem módosíthat rendelést.")
    return sor


def _uj_statuszu_kell(sor: sqlite3.Row) -> None:
    if sor["statusz"] != "új":
        raise UzletiHiba("A tételek csak új státuszú rendelésnél módosíthatók.")


def tetel_hozzaad(rendeles_id: int, felhasznalo_id: int, termek_id: int, db: int = 1) -> Rendeles:
    """Ugyanaz a termék újra: a meglévő tétel darabszáma nő."""
    if db < 1:
        raise ValidacioHiba("A darabszám legalább 1.")
    with kapcsolat() as conn:
        sor = _sajat_rendeles(conn, rendeles_id, felhasznalo_id)
        _uj_statuszu_kell(sor)
        termek = _termek_betolt(conn, termek_id)
        if termek is None or not termek.aktiv:
            raise UzletiHiba("Inaktív vagy nem létező termék nem rendelhető.")
        conn.execute(
            """INSERT INTO rendeles_tetel (rendeles_id, termek_id, db, egysegar) VALUES (?, ?, ?, ?)
               ON CONFLICT (rendeles_id, termek_id) DO UPDATE SET db = db + excluded.db""",
            (rendeles_id, termek_id, db, termek.ar),
        )
        return _rendeles_betolt(conn, sor)


def tetel_modosit(rendeles_id: int, felhasznalo_id: int, termek_id: int, db: int) -> Rendeles:
    """Az azóta inaktivált termék darabszáma csak csökkenhet."""
    if db < 1:
        raise ValidacioHiba("A darabszám legalább 1.")
    with kapcsolat() as conn:
        sor = _sajat_rendeles(conn, rendeles_id, felhasznalo_id)
        _uj_statuszu_kell(sor)
        tetel = conn.execute(
            """SELECT rt.db, t.aktiv FROM rendeles_tetel rt JOIN termek t ON t.id = rt.termek_id
               WHERE rt.rendeles_id = ? AND rt.termek_id = ?""", (rendeles_id, termek_id)
        ).fetchone()
        if tetel is None:
            raise NemTalalhato("A termék nem szerepel a rendelésben.")
        if db > tetel["db"] and not tetel["aktiv"]:
            raise UzletiHiba("Inaktív termék mennyisége nem növelhető.")
        conn.execute(
            "UPDATE rendeles_tetel SET db = ? WHERE rendeles_id = ? AND termek_id = ?",
            (db, rendeles_id, termek_id),
        )
        return _rendeles_betolt(conn, sor)


def tetel_torol(rendeles_id: int, felhasznalo_id: int, termek_id: int) -> Rendeles:
    """A rendelés utolsó tétele nem törölhető; helyette a rendelést kell lemondani."""
    with kapcsolat() as conn:
        sor = _sajat_rendeles(conn, rendeles_id, felhasznalo_id)
        _uj_statuszu_kell(sor)
        if not conn.execute("SELECT 1 FROM rendeles_tetel WHERE rendeles_id = ? AND termek_id = ?",
                            (rendeles_id, termek_id)).fetchone():
            raise NemTalalhato("A termék nem szerepel a rendelésben.")
        darab = conn.execute("SELECT count(*) FROM rendeles_tetel WHERE rendeles_id = ?",
                             (rendeles_id,)).fetchone()[0]
        if darab == 1:
            raise UzletiHiba("A rendelés utolsó tétele nem törölhető, helyette mondd le a rendelést.")
        conn.execute("DELETE FROM rendeles_tetel WHERE rendeles_id = ? AND termek_id = ?",
                     (rendeles_id, termek_id))
        return _rendeles_betolt(conn, sor)


def _feltetelesen(conn: sqlite3.Connection, rendeles_id: int, sql: str, param: tuple,
                  uzenet: str) -> Rendeles:
    """Egy feltételes UPDATE a rendelésen; ha egy sort sem érint, üzleti hiba."""
    if conn.execute(sql, param).rowcount == 0:
        raise UzletiHiba(uzenet)
    return _rendeles_betolt(conn, _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található"))


def rendeles_lemond(rendeles_id: int, felhasznalo_id: int) -> Rendeles:
    """Csak új státuszú rendelés mondható le, és csak a megrendelő mondhatja le."""
    with kapcsolat() as conn:
        _sajat_rendeles(conn, rendeles_id, felhasznalo_id)
        return _feltetelesen(
            conn, rendeles_id,
            "UPDATE rendeles SET statusz = 'lemondva' WHERE id = ? AND statusz = 'új'",
            (rendeles_id,), "Csak új státuszú rendelés mondható le.")


def rendeles_ertekel(rendeles_id: int, felhasznalo_id: int, ertekeles: int) -> Rendeles:
    """Kiszállított rendelés egyszer értékelhető, 1 és 5 között."""
    if ertekeles not in (1, 2, 3, 4, 5):
        raise ValidacioHiba("Az értékelés 1 és 5 közötti egész szám.")
    with kapcsolat() as conn:
        _sajat_rendeles(conn, rendeles_id, felhasznalo_id)
        return _feltetelesen(
            conn, rendeles_id,
            """UPDATE rendeles SET ertekeles = ?
               WHERE id = ? AND statusz = 'kiszállítva' AND ertekeles IS NULL""",
            (ertekeles, rendeles_id), "Csak kiszállított, még nem értékelt rendelés értékelhető.")


def rendeles_jatt(rendeles_id: int, felhasznalo_id: int, jatt: int) -> Rendeles:
    """Jatt kiszállítás után, kártyás fizetésnél, egyszer adható (ck_rendeles_jatt)."""
    if jatt <= 0:
        raise ValidacioHiba("A jatt pozitív egész szám.")
    with kapcsolat() as conn:
        _sajat_rendeles(conn, rendeles_id, felhasznalo_id)
        return _feltetelesen(
            conn, rendeles_id,
            """UPDATE rendeles SET jatt = ?
               WHERE id = ? AND statusz = 'kiszállítva' AND fizetesi_mod = 'kartya' AND jatt IS NULL""",
            (jatt, rendeles_id), "Jatt csak kiszállított, kártyával fizetett rendeléshez adható, egyszer.")


# ---------------------------------------------------------------------------
# Rendelés: futár és konyha (új -> elfogadva -> készül -> úton -> kiszállítva)
# ---------------------------------------------------------------------------
def felveheto_rendelesek(futar_id: int, limit: int | None = None, offset: int = 0) -> list[Rendeles]:
    """Új, futár nélküli rendelések a futár hatósugarán belül; a prioritásosak elöl."""
    with kapcsolat() as conn:
        futar = _letezik(conn, "futar", futar_id, "Futár nem található")
        sql = """SELECT * FROM rendeles WHERE statusz = 'új' AND futar_id IS NULL AND km <= ?
                 ORDER BY prioritas DESC, letrehozva, id"""
        par: list = [futar["hatosugar_km"]]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            par += [limit, offset]
        return [_rendeles_betolt(conn, s) for s in conn.execute(sql, par).fetchall()]


def rendeles_felvesz(rendeles_id: int, futar_id: int) -> Rendeles:
    """A futár felveszi a rendelést (új -> elfogadva). Egy tranzakcióban: a futár
    ellenőrzése és 'uton'-ra állítása, majd egy feltételes UPDATE a rendelésen,
    így egy rendelést nem vehet fel két futár, és egy futárnak egy aktív rendelése lehet."""
    with kapcsolat() as conn:
        futar = _letezik(conn, "futar", futar_id, "Futár nem található")
        rendeles = _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található")
        if not futar["aktiv"]:
            raise UzletiHiba("Inaktív futár nem vehet fel rendelést.")
        if rendeles["km"] is not None and rendeles["km"] > futar["hatosugar_km"]:
            raise UzletiHiba("A rendelés a futár hatósugarán kívül esik.")
        cur = conn.execute(
            f"""UPDATE futar SET allapot = 'uton'
                WHERE id = ? AND aktiv = 1 AND allapot = 'elerheto' AND NOT EXISTS (
                    SELECT 1 FROM rendeles WHERE futar_id = futar.id AND statusz IN {_AKTIV_IN})""",
            (futar_id,),
        )
        if cur.rowcount == 0:
            raise UzletiHiba("Csak elérhető, aktív rendelés nélküli futár vehet fel rendelést.")
        return _feltetelesen(
            conn, rendeles_id,
            """UPDATE rendeles SET futar_id = ?, statusz = 'elfogadva'
               WHERE id = ? AND futar_id IS NULL AND statusz = 'új'""",
            (futar_id, rendeles_id), "A rendelést már felvették, vagy nem új státuszú.")


def rendeles_keszul(rendeles_id: int) -> Rendeles:
    """A konyha elkezdi készíteni a futár által elfogadott rendelést (elfogadva -> készül)."""
    with kapcsolat() as conn:
        _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található")
        return _feltetelesen(
            conn, rendeles_id,
            "UPDATE rendeles SET statusz = 'készül' WHERE id = ? AND statusz = 'elfogadva'",
            (rendeles_id,), "Csak elfogadott rendelés készíthető.")


def rendeles_atvesz(rendeles_id: int, futar_id: int) -> Rendeles:
    """A futár átveszi a rendelést a konyhától (elfogadva vagy készül -> úton)."""
    with kapcsolat() as conn:
        _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található")
        return _feltetelesen(
            conn, rendeles_id,
            """UPDATE rendeles SET statusz = 'úton'
               WHERE id = ? AND futar_id = ? AND statusz IN ('elfogadva', 'készül')""",
            (rendeles_id, futar_id), "Csak a futárhoz rendelt, elfogadott vagy készülő rendelés vehető át.")


def rendeles_kiszallit(rendeles_id: int, futar_id: int) -> Rendeles:
    """úton -> kiszállítva, és a futár újra elérhető; egy tranzakcióban.
    A kiszallitva_ido-t a trg_rendeles_kiszallitva trigger tölti ki."""
    with kapcsolat() as conn:
        _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található")
        if conn.execute(
            "UPDATE rendeles SET statusz = 'kiszállítva' WHERE id = ? AND futar_id = ? AND statusz = 'úton'",
            (rendeles_id, futar_id),
        ).rowcount == 0:
            raise UzletiHiba("Csak a futárhoz rendelt, úton lévő rendelés szállítható ki.")
        conn.execute("UPDATE futar SET allapot = 'elerheto' WHERE id = ?", (futar_id,))
        return _rendeles_betolt(conn, _letezik(conn, "rendeles", rendeles_id, "Rendelés nem található"))


# ---------------------------------------------------------------------------
# Rugalmas szűrők: táblánként EGY függvény, minden paraméter opcionális
#
#   - None  = nincs szűrés erre a mezőre
#   - lista = bármelyik érték jó (IN), pl. statusz=["új", "úton"]
#   - *_min / *_max = határértékek, *_tartalmaz = szövegrészlet keresése
#   - rendezes / csokkeno / limit / offset: sorrend és lapozás
# Az értékek mindig ?-ként mennek, az oszlopnevek pedig fehérlistáról jönnek.
# ---------------------------------------------------------------------------
def _egyenlo(felt: list, par: list, oszlop: str, ertek) -> None:
    """oszlop = ?  (vagy IN (...) listánál). None esetén nem szűr."""
    if ertek is None:
        return
    if isinstance(ertek, (list, tuple, set)):
        if not ertek:                       # üres lista: semmi sem felel meg
            felt.append("1 = 0")
            return
        felt.append(f"{oszlop} IN ({', '.join('?' * len(ertek))})")
        par.extend(ertek)
    else:
        felt.append(f"{oszlop} = ?")
        par.append(ertek)


def _tartomany(felt: list, par: list, oszlop: str, minimum, maximum) -> None:
    if minimum is not None:
        felt.append(f"{oszlop} >= ?")
        par.append(minimum)
    if maximum is not None:
        felt.append(f"{oszlop} <= ?")
        par.append(maximum)


def _tartalmaz(felt: list, par: list, oszlop: str, szoveg: str | None) -> None:
    """Szövegrészlet keresése; a %, _ jeleket szó szerint kezeli."""
    if not szoveg:
        return
    escape = szoveg.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    felt.append(f"{oszlop} LIKE ? ESCAPE '\\'")
    par.append(f"%{escape}%")


def _logikai(felt: list, oszlop: str, ertek: bool | None) -> None:
    if ertek is not None:
        felt.append(f"{oszlop} = {1 if ertek else 0}")


def _sorok(conn: sqlite3.Connection, tabla: str, felt: list, par: list,
           rendezes: str | None, csokkeno: bool, limit: int | None,
           offset: int, engedett_rendezes: set[str]) -> list[sqlite3.Row]:
    """Összeállítja és lefuttatja a SELECT-et a feltételekből."""
    sql = f"SELECT * FROM {tabla}"
    if felt:
        sql += " WHERE " + " AND ".join(felt)
    if rendezes is not None:
        if rendezes not in engedett_rendezes:
            raise ValidacioHiba(f"Érvénytelen rendezés: {rendezes}. "
                                f"Lehetséges: {sorted(engedett_rendezes)}")
        sql += f" ORDER BY {rendezes} {'DESC' if csokkeno else 'ASC'}, id"
    else:
        sql += " ORDER BY id"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        par = par + [limit, offset]
    return conn.execute(sql, par).fetchall()


def felhasznalok_szur(*, nev_tartalmaz: str | None = None,
                      cim_tartalmaz: str | None = None,
                      telszam: str | None = None,
                      email: str | None = None,
                      email_tartalmaz: str | None = None,
                      admin: bool | None = None,
                      aktiv: bool | None = None,
                      rendezes: str | None = None, csokkeno: bool = False,
                      limit: int | None = None, offset: int = 0) -> list[Felhasznalo]:
    felt, par = [], []
    _tartalmaz(felt, par, "nev", nev_tartalmaz)
    _tartalmaz(felt, par, "cim", cim_tartalmaz)
    _egyenlo(felt, par, "telszam", telszam)
    _egyenlo(felt, par, "email", email.strip().lower() if email else None)
    _tartalmaz(felt, par, "email", email_tartalmaz)
    _logikai(felt, "isAdmin", admin)
    _logikai(felt, "aktiv", aktiv)
    with kapcsolat() as conn:
        sorok = _sorok(conn, "felhasznalo", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "nev", "cim", "email"})
        return [Felhasznalo.sorbol(s) for s in sorok]


def futarok_szur(*, jarmu: str | list[str] | None = None,
                 allapot: str | list[str] | None = None,
                 aktiv: bool | None = None,
                 min_hatosugar_km: int | None = None,
                 nev_tartalmaz: str | None = None,
                 rendezes: str | None = None, csokkeno: bool = False,
                 limit: int | None = None, offset: int = 0) -> list[Futar]:
    felt, par = [], []
    _egyenlo(felt, par, "jarmu", jarmu)
    _egyenlo(felt, par, "allapot", allapot)
    _logikai(felt, "aktiv", aktiv)
    _tartomany(felt, par, "hatosugar_km", min_hatosugar_km, None)
    _tartalmaz(felt, par, "nev", nev_tartalmaz)
    with kapcsolat() as conn:
        sorok = _sorok(conn, "futar", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "nev", "hatosugar_km"})
        return [Futar.sorbol(s) for s in sorok]


def termekek_szur(*, tipus: str | None = None,
                  fogas: str | list[str] | None = None,
                  ar_min: int | None = None, ar_max: int | None = None,
                  nev_tartalmaz: str | None = None,
                  max_elkeszitesi_ido: int | None = None,
                  prioritas: int | None = None,
                  aktiv: bool | None = None,
                  nem_tartalmaz_allergen: list[int] | None = None,
                  rendezes: str | None = None, csokkeno: bool = False,
                  limit: int | None = None, offset: int = 0) -> list[Termek]:
    """nem_tartalmaz_allergen: allergénkódok, amelyek egyikét sem tartalmazhatja."""
    felt, par = [], []
    _egyenlo(felt, par, "tipus", tipus)
    _egyenlo(felt, par, "fogas", fogas)
    _tartomany(felt, par, "ar", ar_min, ar_max)
    _tartalmaz(felt, par, "nev", nev_tartalmaz)
    _tartomany(felt, par, "elkeszitesi_ido", None, max_elkeszitesi_ido)
    _egyenlo(felt, par, "prioritas", prioritas)
    _logikai(felt, "aktiv", aktiv)
    if nem_tartalmaz_allergen:
        felt.append(f"""NOT EXISTS (SELECT 1 FROM termek_allergen ta
                        WHERE ta.termek_id = termek.id
                          AND ta.allergen_kod IN ({', '.join('?' * len(nem_tartalmaz_allergen))}))""")
        par.extend(nem_tartalmaz_allergen)
    with kapcsolat() as conn:
        sorok = _sorok(conn, "termek", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "nev", "ar", "elkeszitesi_ido", "prioritas"})
        return [_termek_betolt(conn, s["id"]) for s in sorok]


def rendelesek_szur(*, felhasznalo_id: int | None = None,
                    futar_id: int | None = None,
                    statusz: str | list[str] | None = None,
                    fizetesi_mod: str | None = None,
                    prioritas: int | None = None,
                    szamla: int | None = None,
                    km_min: int | None = None, km_max: int | None = None,
                    ertekeles_min: int | None = None,
                    ertekeles_max: int | None = None,
                    van_jatt: bool | None = None,
                    cim_tartalmaz: str | None = None,
                    termek_id: int | None = None,
                    letrehozva_tol: str | None = None,
                    letrehozva_ig: str | None = None,
                    rendezes: str | None = None, csokkeno: bool = False,
                    limit: int | None = None, offset: int = 0) -> list[Rendeles]:
    """van_jatt: True = csak borravalós, False = csak borravaló nélküli.
    termek_id: csak azok a rendelések, amelyek tartalmazzák ezt a terméket.
    letrehozva_tol / _ig: 'ÉÉÉÉ-HH-NN' vagy 'ÉÉÉÉ-HH-NN óó:pp:mm' (mindkét vége zárt)."""
    felt, par = [], []
    _egyenlo(felt, par, "felhasznalo_id", felhasznalo_id)
    _egyenlo(felt, par, "futar_id", futar_id)
    _egyenlo(felt, par, "statusz", statusz)
    _egyenlo(felt, par, "fizetesi_mod", fizetesi_mod)
    _egyenlo(felt, par, "prioritas", prioritas)
    _egyenlo(felt, par, "szamla", szamla)
    _tartomany(felt, par, "km", km_min, km_max)
    _tartomany(felt, par, "ertekeles", ertekeles_min, ertekeles_max)
    if van_jatt is not None:
        felt.append("jatt IS NOT NULL" if van_jatt else "jatt IS NULL")
    _tartalmaz(felt, par, "cim", cim_tartalmaz)
    if termek_id is not None:
        felt.append("""EXISTS (SELECT 1 FROM rendeles_tetel rt
                       WHERE rt.rendeles_id = rendeles.id AND rt.termek_id = ?)""")
        par.append(termek_id)
    if letrehozva_tol is not None:
        felt.append("letrehozva >= ?")
        par.append(letrehozva_tol)
    if letrehozva_ig is not None:
        # egy nap végéig, ha csak dátum jön
        felt.append("letrehozva <= ?")
        par.append(letrehozva_ig if len(letrehozva_ig) > 10 else letrehozva_ig + " 23:59:59")
    with kapcsolat() as conn:
        sorok = _sorok(conn, "rendeles", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "km", "ertekeles", "jatt", "statusz", "letrehozva"})
        return [_rendeles_betolt(conn, s) for s in sorok]


if __name__ == "__main__":
    print(db_path(), db_path().exists())
