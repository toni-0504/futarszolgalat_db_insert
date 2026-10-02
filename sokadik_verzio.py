import sqlite3
from pathlib import Path
from futarszolgalat_db_insert.db import kapcsolat

DB_PATH = Path(__file__).resolve().parent / "futarszolgalat.db"

# ===========================================================================
# FELHASZNÁLÓ
# ===========================================================================

def felhasznalo_letrehoz(nev: str, cim: str, telszam: str) -> int:
    """Új felhasználó létrehozása. Az adatbázis séma alapján az email nem szerepel."""
    nev, cim, telszam = (str(x or "").strip() for x in (nev, cim, telszam))
    if not (nev and cim and telszam):
        raise ValueError("A név, a cím és a telefonszám kitöltése kötelező.")
    
    with kapcsolat() as conn:
        cur = conn.execute(
            "INSERT INTO felhasznalo (nev, cim, telszam) VALUES (?, ?, ?)",
            (nev, cim, telszam),
        )
        return cur.lastrowid

def felhasznalo_lekerdez(felhasznalo_id: int) -> dict | None:
    """Lekérdezi a felhasználót ID alapján."""
    with kapcsolat() as conn:
        sor = conn.execute("SELECT * FROM felhasznalo WHERE id = ?", (felhasznalo_id,)).fetchone()
        return dict(sor) if sor else None

def felhasznalo_modosit(felhasznalo_id: int, nev: str, cim: str, telszam: str, email: str) -> bool:
    """Frissíti a megadott ID-jú felhasználó adatait."""
    nev, cim, telszam, email = (str(x or "").strip() for x in (nev, cim, telszam, email))
    if not (nev and cim and telszam and email):
        raise ValueError("A név, a cím, a telefonszám és az email kötelező.")
    with kapcsolat() as conn:
        cur = conn.execute(
            "UPDATE felhasznalo SET nev = ?, cim = ?, telszam = ?, email = ? WHERE id = ?",
            (nev, cim, telszam, email, felhasznalo_id),
        )
        return cur.rowcount > 0

def felhasznalo_torol(felhasznalo_id: int) -> bool:
    """Figyelem: az ON DELETE CASCADE miatt a rendelései is törlődnek."""
    with kapcsolat() as conn:
        cur = conn.execute("DELETE FROM felhasznalo WHERE id = ?", (felhasznalo_id,))
        return cur.rowcount > 0

# ===========================================================================
# FUTÁR
# ===========================================================================

def futar_lekerdez(futar_id: int) -> dict | None:
    """Futár alapadatainak lekérdezése."""
    with kapcsolat() as conn:
        sor = conn.execute("SELECT * FROM futar WHERE id = ?", (futar_id,)).fetchone()
        return dict(sor) if sor else None

def futar_allapot_modosit(futar_id: int, allapot: str) -> bool:
    """Frissíti a futár állapotát."""
    if allapot not in ("elerheto", "uton", "szunet"):
        raise ValueError("Érvénytelen állapot.")
    with kapcsolat() as conn:
        cur = conn.execute("UPDATE futar SET allapot = ? WHERE id = ?", (allapot, futar_id))
        return cur.rowcount > 0

def elerheto_futarok(jarmu: str | None = None) -> list[dict]:
    """Elérhető futárok listája, opcionálisan járműre szűrve."""
    sql = "SELECT * FROM futar WHERE allapot = 'elerheto'"
    param = []
    if jarmu:
        sql += " AND jarmu = ?"
        param.append(jarmu)
    with kapcsolat() as conn:
        return [dict(s) for s in conn.execute(sql, tuple(param))]

# ===========================================================================
# TERMÉK ÉS ALLERGÉN
# ===========================================================================

def termek_lekerdez(termek_id: int) -> dict | None:
    """Lekérdez egy terméket az allergénjeivel együtt."""
    with kapcsolat() as conn:
        sor = conn.execute("SELECT * FROM termek WHERE id = ?", (termek_id,)).fetchone()
        if not sor:
            return None
            
        termek = dict(sor)
        allergenek = conn.execute(
            """SELECT a.kod, a.nev FROM allergen a
               JOIN termek_allergen ta ON ta.allergen_kod = a.kod
               WHERE ta.termek_id = ?""",
            (termek_id,)
        ).fetchall()
        
        termek["allergenek"] = [dict(a) for a in allergenek]
        return termek

# ===========================================================================
# RENDELÉS
# ===========================================================================

def rendeles_letrehoz(felhasznalo_id: int, futar_id: int, cim: str, fizetesi_mod: str, szamla: int, km: int, tetelek: list[tuple[int, int]], ertekeles: int, prioritas: int = 0, jatt: int | None = None, statusz: str = "új") -> int:
    """
    Rendelés létrehozása.
    `tetelek`: (termek_id, db) párok listája.
    A séma megkötéseinek (CHECK) megfelelően validál.
    """
    if not tetelek:
        raise ValueError("Legalább egy tétel szükséges a rendeléshez.")
    if fizetesi_mod not in ('keszpenz', 'kartya'):
        raise ValueError("A fizetési mód 'keszpenz' vagy 'kartya' lehet.")
    if prioritas not in (0, 1) or szamla not in (0, 1):
        raise ValueError("A prioritás és a számla csak 0 vagy 1 lehet.")
    if jatt is not None and (jatt <= 0 or fizetesi_mod != 'kartya'):
        raise ValueError("Jatt csak kártyás fizetésnél adható, és pozitívnak kell lennie.")
    if ertekeles not in (1, 2, 3, 4, 5):
        raise ValueError("Az értékelés kötelező, és 1-5 közötti egész szám lehet.")
        
    with kapcsolat() as conn:
        cur = conn.execute(
            """INSERT INTO rendeles (felhasznalo_id, futar_id, cim, prioritas,
                                     fizetesi_mod, jatt, szamla, km, statusz, ertekeles)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (felhasznalo_id, futar_id, cim, prioritas, fizetesi_mod, jatt, szamla, km, statusz, ertekeles),
        )
        rendeles_id = cur.lastrowid
        
        conn.executemany(
            "INSERT INTO rendeles_tetel (rendeles_id, termek_id, db) VALUES (?, ?, ?)",
            [(rendeles_id, termek_id, db) for termek_id, db in tetelek],
        )
        return rendeles_id

def rendeles_lekerdez(rendeles_id: int) -> dict | None:
    """A rendelést a tételeivel együtt adja vissza."""
    with kapcsolat() as conn:
        sor = conn.execute("SELECT * FROM rendeles WHERE id = ?", (rendeles_id,)).fetchone()
        if not sor:
            return None
            
        rendeles = dict(sor)
        tetelek = conn.execute(
            """SELECT t.*, rt.db FROM termek t
               JOIN rendeles_tetel rt ON t.id = rt.termek_id
               WHERE rt.rendeles_id = ?""",
            (rendeles_id,)
        ).fetchall()
        
        rendeles["tetelek"] = [dict(t) for t in tetelek]
        return rendeles

def rendeles_statusz_modosit(rendeles_id: int, statusz: str) -> bool:
    """Módosítja a rendelés státuszát."""
    with kapcsolat() as conn:
        cur = conn.execute("UPDATE rendeles SET statusz = ? WHERE id = ?", (statusz, rendeles_id))
        return cur.rowcount > 0

def felhasznalo_rendelesei(felhasznalo_id: int) -> list[dict]:
    """Egy adott felhasználó összes rendelését adja vissza, tételekkel együtt."""
    with kapcsolat() as conn:
        rendeles_idk = conn.execute("SELECT id FROM rendeles WHERE felhasznalo_id = ?", (felhasznalo_id,)).fetchall()
        return [rendeles_lekerdez(sor["id"]) for sor in rendeles_idk]

def futar_rendelesei(futar_id: int) -> list[dict]:
    """Egy adott futárhoz tartozó összes rendelés lekérdezése."""
    with kapcsolat() as conn:
        rendeles_idk = conn.execute("SELECT id FROM rendeles WHERE futar_id = ?", (futar_id,)).fetchall()
        return [rendeles_lekerdez(sor["id"]) for sor in rendeles_idk]


# ===========================================================================
# TESZTELÉS
# ===========================================================================
if __name__ == "__main__":
    print(f"Adatbázis elérési út: {DB_PATH}")
    print(f"Adatbázis létezik: {DB_PATH.exists()}")