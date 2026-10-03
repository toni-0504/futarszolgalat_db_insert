"""Mintaként: SQLite mentés/betöltés a modellek (modellek.py) használatával.

A függvények modellobjektumot fogadnak és adnak vissza. A mentők beállítják az
objektum id-ját is, és több táblát érintő műveletek egy tranzakcióban futnak.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

try:
    from .modellek import (Allergen, Felhasznalo, Futar, FutarPozicio, Rendeles,
                           RendelesTetel, Termek, jelszo_hashel)
except ImportError:
    from modellek import (Allergen, Felhasznalo, Futar, FutarPozicio, Rendeles,
                          RendelesTetel, Termek, jelszo_hashel)

# A script mappájából számoljuk, így mindegy, honnan indítod a programot.
DB_PATH = Path(__file__).resolve().parent / "futarszolgalat.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _schema_biztosit(conn: sqlite3.Connection) -> None:
    """Új adatbázisnál létrehozza a táblákat, réginél kiegészíti a felhasználót."""
    van_tabla = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
    ).fetchone()
    if van_tabla is None:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    oszlopok = {sor["name"] for sor in conn.execute("PRAGMA table_info(felhasznalo)")}
    for nev, definicio in (
        ("email", "TEXT"),
        ("password", "TEXT"),
        ("isAdmin", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if nev not in oszlopok:
            conn.execute(f"ALTER TABLE felhasznalo ADD COLUMN {nev} {definicio}")


# ---------------------------------------------------------------------------
# Kapcsolat
# ---------------------------------------------------------------------------
@contextmanager
def kapcsolat():
    """Siker esetén commit, hiba esetén rollback, a végén mindig zár."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite-ban alapból ki van kapcsolva
    try:
        _schema_biztosit(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Egyszeri adatjavítás a felhasználókon (többször is futtatható)
# ---------------------------------------------------------------------------
def migracio_felhasznalo() -> int:
    """1) A még sima szövegként tárolt jelszavakat hash-eli a 'password' oszlopban.
    2) Egyedivé teszi az emailt (ha nincs duplikált email).
    Visszaadja, hány jelszót hash-elt át."""
    with kapcsolat() as conn:
        regiek = conn.execute(
            """SELECT id, password FROM felhasznalo
               WHERE password IS NOT NULL AND password NOT LIKE 'pbkdf2_sha256$%'"""
        ).fetchall()
        conn.executemany(
            "UPDATE felhasznalo SET password = ? WHERE id = ?",
            [(jelszo_hashel(s["password"]), s["id"]) for s in regiek],
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_felhasznalo_email "
                     "ON felhasznalo(email)")
        return len(regiek)


# ---------------------------------------------------------------------------
# Felhasználó
# ---------------------------------------------------------------------------
def felhasznalo_letrehoz(f: Felhasznalo) -> int:
    """Elmenti a felhasználót, beállítja f.id-t, és visszaadja az új id-t."""
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO felhasznalo (nev, cim, telszam, email, password, isAdmin)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f.nev, f.cim, f.telszam, f.email, f.jelszo_hash, int(f.admin)),
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
               SET nev = ?, cim = ?, telszam = ?, email = ?, password = ?, isAdmin = ?
               WHERE id = ?""",
            (f.nev, f.cim, f.telszam, f.email, f.jelszo_hash, int(f.admin), f.id),
        )
        return cur.rowcount > 0


def felhasznalo_lekerdez_emailre(email: str) -> Felhasznalo | None:
    with kapcsolat() as conn:
        sor = conn.execute(
            "SELECT * FROM felhasznalo WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return Felhasznalo.sorbol(sor) if sor else None


def bejelentkezes(email: str, jelszo: str) -> Felhasznalo | None:
    """A felhasználót adja vissza, ha az email és a jelszó helyes, különben None.
    Szándékosan nem árulja el, hogy az email vagy a jelszó volt-e rossz."""
    f = felhasznalo_lekerdez_emailre(email)
    return f if f and f.jelszo_helyes(jelszo) else None


def felhasznalo_torol(felhasznalo_id: int) -> bool:
    """Figyelem: az ON DELETE CASCADE miatt a rendelései is törlődnek."""
    with kapcsolat() as conn:
        cur = conn.execute("DELETE FROM felhasznalo WHERE id = ?", (felhasznalo_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Futár
# ---------------------------------------------------------------------------
def futar_letrehoz(f: Futar) -> int:
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO futar (nev, telszam, jarmu, ember, allapot, hatosugar_km)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f.nev, f.telszam, f.jarmu, f.ember, f.allapot, f.hatosugar_km),
        )
        f.id = cur.lastrowid
        return f.id


def futar_lekerdez(futar_id: int) -> Futar | None:
    with kapcsolat() as conn:
        sor = conn.execute("SELECT * FROM futar WHERE id = ?", (futar_id,)).fetchone()
        return Futar.sorbol(sor) if sor else None


def futar_allapot_modosit(futar_id: int, allapot: str) -> bool:
    with kapcsolat() as conn:
        cur = conn.execute(
            "UPDATE futar SET allapot = ? WHERE id = ?", (allapot, futar_id)
        )
        return cur.rowcount > 0


def elerheto_futarok(jarmu: str | None = None) -> list[Futar]:
    sql = "SELECT * FROM futar WHERE allapot = 'elerheto'"
    param: tuple = ()
    if jarmu:
        sql += " AND jarmu = ?"
        param = (jarmu,)
    with kapcsolat() as conn:
        return [Futar.sorbol(s) for s in conn.execute(sql, param)]


# ---------------------------------------------------------------------------
# Futár pozíciója (az SQL-ben az oszlop neve: futarID)
# ---------------------------------------------------------------------------
def futar_pozicio_letrehoz(p: FutarPozicio) -> int:
    with kapcsolat() as conn:
        cur = conn.execute(
            "INSERT INTO futar_pozicio (futarID, gps_x, gps_y, cim) VALUES (?, ?, ?, ?)",
            (p.futar_id, p.gps_x, p.gps_y, p.cim),
        )
        p.id = cur.lastrowid
        return p.id


def futar_pozicio_lekerdez(futar_id: int) -> list[FutarPozicio]:
    """A futár pozíciói, a legújabb (legnagyobb id) elöl."""
    with kapcsolat() as conn:
        return [FutarPozicio.sorbol(s) for s in conn.execute(
            "SELECT * FROM futar_pozicio WHERE futarID = ? ORDER BY id DESC",
            (futar_id,))]


# ---------------------------------------------------------------------------
# Termék (+ allergének a kapcsolótáblában)
# ---------------------------------------------------------------------------
def termek_letrehoz(t: Termek) -> int:
    """A terméket és az allergénkapcsolatait egy tranzakcióban menti."""
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO termek (tipus, nev, fogas, leiras, ar, elkeszitesi_ido, prioritas)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (t.tipus, t.nev, t.fogas, t.leiras, t.ar, t.elkeszitesi_ido, t.prioritas),
        )
        t.id = cur.lastrowid
        conn.executemany(
            "INSERT INTO termek_allergen (termek_id, allergen_kod) VALUES (?, ?)",
            [(t.id, a.kod) for a in t.allergenek],
        )
        return t.id


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
           WHERE ta.termek_id = ?""", (termek_id,))]
    return Termek.sorbol(sor, allergenek)


def allergenek_lekerdez() -> list[Allergen]:
    with kapcsolat() as conn:
        return [Allergen.sorbol(s) for s in conn.execute("SELECT * FROM allergen")]


# ---------------------------------------------------------------------------
# Rendelés (fejléc + tételek együtt)
# ---------------------------------------------------------------------------
def rendeles_letrehoz(r: Rendeles) -> int:
    """A fejléc és az összes tétel vagy mind elmentődik, vagy egyik sem."""
    if r.ertekeles is None:
        # Az SQL-ben az ertekeles NOT NULL, ezt a csapatnak kell eldöntenie.
        raise ValueError("Az 'ertekeles' az adatbázisban kötelező mező.")
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO rendeles (felhasznalo_id, futar_id, cim, prioritas,
                                     fizetesi_mod, jatt, szamla, km, statusz, ertekeles)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r.felhasznalo_id, r.futar_id, r.cim, r.prioritas, r.fizetesi_mod,
             r.jatt, r.szamla, r.km, r.statusz, r.ertekeles),
        )
        r.id = cur.lastrowid
        conn.executemany(
            "INSERT INTO rendeles_tetel (rendeles_id, termek_id, db) VALUES (?, ?, ?)",
            [(r.id, t.termek.id, t.db) for t in r.tetelek],
        )
        return r.id


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
        RendelesTetel(_termek_betolt(conn, ts["termek_id"]), ts["db"])
        for ts in conn.execute(
            "SELECT termek_id, db FROM rendeles_tetel WHERE rendeles_id = ?",
            (sor["id"],))
    ]
    return Rendeles(
        id=sor["id"], felhasznalo_id=sor["felhasznalo_id"],
        futar_id=sor["futar_id"], cim=sor["cim"], prioritas=sor["prioritas"],
        fizetesi_mod=sor["fizetesi_mod"], jatt=sor["jatt"], szamla=sor["szamla"],
        km=sor["km"], statusz=sor["statusz"], ertekeles=sor["ertekeles"],
        tetelek=tetelek,
    )


def rendeles_statusz_modosit(rendeles_id: int, statusz: str) -> bool:
    with kapcsolat() as conn:
        cur = conn.execute(
            "UPDATE rendeles SET statusz = ? WHERE id = ?", (statusz, rendeles_id)
        )
        return cur.rowcount > 0


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


def _sorok(conn: sqlite3.Connection, tabla: str, felt: list, par: list,
           rendezes: str | None, csokkeno: bool, limit: int | None,
           offset: int, engedett_rendezes: set[str]) -> list[sqlite3.Row]:
    """Összeállítja és lefuttatja a SELECT-et a feltételekből."""
    sql = f"SELECT * FROM {tabla}"
    if felt:
        sql += " WHERE " + " AND ".join(felt)
    if rendezes is not None:
        if rendezes not in engedett_rendezes:
            raise ValueError(f"Érvénytelen rendezés: {rendezes}. "
                             f"Lehetséges: {sorted(engedett_rendezes)}")
        sql += f" ORDER BY {rendezes} {'DESC' if csokkeno else 'ASC'}"
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
                      rendezes: str | None = None, csokkeno: bool = False,
                      limit: int | None = None, offset: int = 0) -> list[Felhasznalo]:
    felt, par = [], []
    _tartalmaz(felt, par, "nev", nev_tartalmaz)
    _tartalmaz(felt, par, "cim", cim_tartalmaz)
    _egyenlo(felt, par, "telszam", telszam)
    _egyenlo(felt, par, "email", email.strip().lower() if email else None)
    _tartalmaz(felt, par, "email", email_tartalmaz)
    if admin is not None:
        felt.append("isAdmin = 1" if admin else "COALESCE(isAdmin, 0) = 0")
    with kapcsolat() as conn:
        sorok = _sorok(conn, "felhasznalo", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "nev", "cim", "email"})
        return [Felhasznalo.sorbol(s) for s in sorok]


def futarok_szur(*, jarmu: str | list[str] | None = None,
                 allapot: str | list[str] | None = None,
                 ember: int | None = None,
                 min_hatosugar_km: int | None = None,
                 nev_tartalmaz: str | None = None,
                 rendezes: str | None = None, csokkeno: bool = False,
                 limit: int | None = None, offset: int = 0) -> list[Futar]:
    felt, par = [], []
    _egyenlo(felt, par, "jarmu", jarmu)
    _egyenlo(felt, par, "allapot", allapot)
    _egyenlo(felt, par, "ember", ember)
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
    if nem_tartalmaz_allergen:
        felt.append(f"""NOT EXISTS (SELECT 1 FROM termek_allergen ta
                        WHERE ta.termek_id = termek.id
                          AND ta.allergen_kod IN ({', '.join('?' * len(nem_tartalmaz_allergen))}))""")
        par.extend(nem_tartalmaz_allergen)
    with kapcsolat() as conn:
        sorok = _sorok(conn, "termek", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "nev", "ar", "elkeszitesi_ido"})
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
                    rendezes: str | None = None, csokkeno: bool = False,
                    limit: int | None = None, offset: int = 0) -> list[Rendeles]:
    """van_jatt: True = csak borravalós, False = csak borravaló nélküli.
    termek_id: csak azok a rendelések, amelyek tartalmazzák ezt a terméket."""
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
    with kapcsolat() as conn:
        sorok = _sorok(conn, "rendeles", felt, par, rendezes, csokkeno,
                       limit, offset, {"id", "km", "ertekeles", "jatt", "statusz"})
        return [_rendeles_betolt(conn, s) for s in sorok]


# ---------------------------------------------------------------------------
# Gyors kipróbálás: FIGYELEM, ez TÉNYLEGESEN ír az adatbázisba!
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(DB_PATH, DB_PATH.exists())

    migracio_felhasznalo()   # a régi sima jelszavak hash-elése, többször is futtatható
    uj = Felhasznalo.regisztral("Teszt Elek", "Budapest, Fő utca 1.", "+36301234567",
                                "teszt.elek@example.com", "titkos1234")
    felhasznalo_letrehoz(uj)
    print("Mentve, id:", uj.id)
    print("Visszaolvasva:", felhasznalo_lekerdez(uj.id))
