"""
Futárszolgálat REST API
Indítás: uvicorn api:app --reload --port 5000
Telepítés: pip install fastapi uvicorn
"""

# A FastAPI maga a keretrendszer, HTTPException a hibakezeléshez
from fastapi import FastAPI, HTTPException

# A Pydantic modell leírja, milyen JSON-t vár az API a PHP-tól
from pydantic import BaseModel

# A saját függvényeink – egy sor sem változik bennük
if __package__:
    from .sokadik_verzio import (
        felhasznalo_letrehoz,
        felhasznalo_lekerdez,
        futar_lekerdez,
        futar_allapot_modosit,
        elerheto_futarok,
        termek_lekerdez,
        rendeles_letrehoz,
        rendeles_lekerdez,
        rendeles_statusz_modosit,
        felhasznalo_rendelesei,
        futar_rendelesei,
    )
else:
    from sokadik_verzio import (
        felhasznalo_letrehoz,
        felhasznalo_lekerdez,
        futar_lekerdez,
        futar_allapot_modosit,
        elerheto_futarok,
        termek_lekerdez,
        rendeles_letrehoz,
        rendeles_lekerdez,
        rendeles_statusz_modosit,
        felhasznalo_rendelesei,
        futar_rendelesei,
    )

# Ez maga az alkalmazás – minden végpont ehhez fog tartozni
app = FastAPI(title="Futárszolgálat API")


# ---------------------------------------------------------------------------
# REQUEST MODELLEK
# Ezek mondják meg a FastAPI-nak (és a PHP csapatnak), milyen mezőket várunk
# POST/PUT kéréseknél. A neve convention: XxxRequest.
# ---------------------------------------------------------------------------

class FelhasznaloLetrehozRequest(BaseModel):
    nev: str
    cim: str
    telszam: str

class FutarAllapotRequest(BaseModel):
    # csak az állapotot küldjük, a futár ID-ja az URL-ben lesz
    allapot: str

class RendelesLetrehozRequest(BaseModel):
    felhasznalo_id: int
    futar_id: int
    cim: str
    fizetesi_mod: str
    szamla: int                      # 0 vagy 1
    km: int
    tetelek: list[tuple[int, int]]   # [(termek_id, db), ...]
    ertekeles: int                   # 1–5
    prioritas: int = 0               # alapértelmezett: 0
    jatt: int | None = None          # opcionális
    statusz: str = "új"              # alapértelmezett: "új"

class RendelesStatuszRequest(BaseModel):
    statusz: str


# ---------------------------------------------------------------------------
# SEGÉDFÜGGVÉNY
# Ha None-t kap (pl. nem létező ID), automatikusan 404-et dob vissza.
# Így minden végpontban nem kell ugyanezt kézzel írni.
# ---------------------------------------------------------------------------

def _vagy_404(ertek, uzenet: str = "Nem található"):
    if ertek is None:
        raise HTTPException(status_code=404, detail=uzenet)
    return ertek


# ---------------------------------------------------------------------------
# FELHASZNÁLÓ VÉGPONTOK
# ---------------------------------------------------------------------------

# POST /felhasznalo → új felhasználó létrehozása
# A 201-es státuszkód jelenti, hogy sikeresen létrehoztunk valamit
@app.post("/felhasznalo", status_code=201)
def ep_felhasznalo_letrehoz(body: FelhasznaloLetrehozRequest):
    # body.nev, body.cim, body.telszam automatikusan kiolvasódik a JSON-ból
    try:
        uj_id = felhasznalo_letrehoz(body.nev, body.cim, body.telszam)
        return {"id": uj_id}
    except ValueError as e:
        # Ha a függvény ValueError-t dob (pl. üres mező), 400 Bad Request-et küldünk
        raise HTTPException(status_code=400, detail=str(e))

# GET /felhasznalo/42 → a 42-es ID-jú felhasználó adatai
@app.get("/felhasznalo/{felhasznalo_id}")
def ep_felhasznalo_lekerdez(felhasznalo_id: int):
    # Az URL-ből kiolvasott számot a FastAPI automatikusan int-té alakítja
    return _vagy_404(felhasznalo_lekerdez(felhasznalo_id), "Felhasználó nem található")

# GET /felhasznalo/42/rendelesek → a 42-es felhasználó összes rendelése
@app.get("/felhasznalo/{felhasznalo_id}/rendelesek")
def ep_felhasznalo_rendelesei(felhasznalo_id: int):
    return felhasznalo_rendelesei(felhasznalo_id)


# ---------------------------------------------------------------------------
# FUTÁR VÉGPONTOK
# ---------------------------------------------------------------------------

# GET /futar/elerheto → összes elérhető futár
# GET /futar/elerheto?jarmu=dron → csak a drónos futárok
# A ?jarmu=dron egy query paraméter – a FastAPI automatikusan kezeli
@app.get("/futar/elerheto")
def ep_elerheto_futarok(jarmu: str | None = None):
    return elerheto_futarok(jarmu)

# GET /futar/7 → a 7-es futár adatai
@app.get("/futar/{futar_id}")
def ep_futar_lekerdez(futar_id: int):
    return _vagy_404(futar_lekerdez(futar_id), "Futár nem található")

# PATCH /futar/7/allapot → csak az állapotot frissítjük, nem az egész futárt
# A PATCH módszer részleges frissítésre való (nem PUT, mert nem küldünk mindent)
@app.patch("/futar/{futar_id}/allapot")
def ep_futar_allapot_modosit(futar_id: int, body: FutarAllapotRequest):
    try:
        if not futar_allapot_modosit(futar_id, body.allapot):
            raise HTTPException(status_code=404, detail="Futár nem található")
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# GET /futar/7/rendelesek → a 7-es futár összes rendelése
@app.get("/futar/{futar_id}/rendelesek")
def ep_futar_rendelesei(futar_id: int):
    return futar_rendelesei(futar_id)


# ---------------------------------------------------------------------------
# TERMÉK VÉGPONTOK
# ---------------------------------------------------------------------------

# GET /termek/42 → a 42-es termék adatai (allergénekkel együtt)
@app.get("/termek/{termek_id}")
def ep_termek_lekerdez(termek_id: int):
    return _vagy_404(termek_lekerdez(termek_id), "Termék nem található")


# ---------------------------------------------------------------------------
# RENDELÉS VÉGPONTOK
# ---------------------------------------------------------------------------

# POST /rendeles → új rendelés létrehozása
@app.post("/rendeles", status_code=201)
def ep_rendeles_letrehoz(body: RendelesLetrehozRequest):
    try:
        uj_id = rendeles_letrehoz(
            body.felhasznalo_id,
            body.futar_id,
            body.cim,
            body.fizetesi_mod,
            body.szamla,
            body.km,
            body.tetelek,
            body.ertekeles,
            body.prioritas,
            body.jatt,
            body.statusz,
        )
        return {"id": uj_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# GET /rendeles/99 → a 99-es rendelés adatai tételekkel
@app.get("/rendeles/{rendeles_id}")
def ep_rendeles_lekerdez(rendeles_id: int):
    return _vagy_404(rendeles_lekerdez(rendeles_id), "Rendelés nem található")

# PATCH /rendeles/99/statusz → csak a státuszt frissítjük
@app.patch("/rendeles/{rendeles_id}/statusz")
def ep_rendeles_statusz_modosit(rendeles_id: int, body: RendelesStatuszRequest):
    if not rendeles_statusz_modosit(rendeles_id, body.statusz):
        raise HTTPException(status_code=404, detail="Rendelés nem található")
    return {"ok": True}