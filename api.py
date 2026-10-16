"""Futárszolgálat REST API."""
import hmac
import os
import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if __package__:
    from . import adatbazis
    from .adatbazis import JogosultsagHiba, NemTalalhato, UzletiHiba
    from .modellek import (
        FUTAR_ALLAPOTOK,
        RENDELES_STATUSZOK,
        Allergen,
        Felhasznalo,
        Futar,
        FutarPozicio,
        Rendeles,
        SzamlazasiAdat,
        Termek,
        ValidacioHiba,
    )
else:
    import adatbazis
    from adatbazis import JogosultsagHiba, NemTalalhato, UzletiHiba
    from modellek import (
        FUTAR_ALLAPOTOK,
        RENDELES_STATUSZOK,
        Allergen,
        Felhasznalo,
        Futar,
        FutarPozicio,
        Rendeles,
        SzamlazasiAdat,
        Termek,
        ValidacioHiba,
    )

app = FastAPI(title="Futárszolgálat API", version="1.0.0")

Jarmu = Literal["auto", "bicikli", "motor"]


# ---------------------------------------------------------------------------
# Védelem és hibakezelés
# ---------------------------------------------------------------------------
@app.middleware("http")
async def api_token_ellenorzes(request: Request, call_next):
    """Ha az API_TOKEN környezeti változó be van állítva, minden író kérés
    (POST, PUT, PATCH, DELETE) 'Authorization: Bearer <token>' fejlécet kér.
    Az olvasó végpontok és a dokumentáció nyilvánosak maradnak."""
    token = os.environ.get("API_TOKEN")
    if token and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        kapott = request.headers.get("authorization", "")
        if not hmac.compare_digest(kapott, f"Bearer {token}"):
            return JSONResponse(status_code=401, content={"detail": "Hiányzó vagy hibás API-token."})
    return await call_next(request)


def _hiba(status_code: int):
    async def kezelo(request: Request, exc: Exception):
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})
    return kezelo


app.add_exception_handler(ValidacioHiba, _hiba(400))
app.add_exception_handler(ValueError, _hiba(400))
app.add_exception_handler(JogosultsagHiba, _hiba(403))
app.add_exception_handler(NemTalalhato, _hiba(404))
app.add_exception_handler(UzletiHiba, _hiba(409))


@app.exception_handler(sqlite3.IntegrityError)
async def _adatbazis_utkozes(request: Request, exc: sqlite3.IntegrityError):
    uzenet = str(exc)
    if "UNIQUE" in uzenet:
        uzenet = "Már létezik ilyen rekord (" + uzenet.split(":")[-1].strip() + ")."
    return JSONResponse(
        status_code=409,
        content={"detail": f"Az adatok ütköznek az adatbázis valamelyik korlátozásával: {uzenet}"},
    )


def _vagy_404(ertek, uzenet: str = "Nem található"):
    if ertek is None:
        raise HTTPException(status_code=404, detail=uzenet)
    return ertek


# ---------------------------------------------------------------------------
# Kérésmodellek
# ---------------------------------------------------------------------------
class FelhasznaloRequest(BaseModel):
    nev: str
    cim: str
    telszam: str
    email: str
    jelszo: str
    admin: bool = False


class FelhasznaloModositRequest(BaseModel):
    nev: str
    cim: str
    telszam: str
    email: str
    jelszo: str | None = None       # None: a jelszó nem változik
    admin: bool = False
    aktiv: bool = True


class BejelentkezesRequest(BaseModel):
    email: str
    jelszo: str


class FutarBejelentkezesRequest(BaseModel):
    nev: str
    telszam: str


class FutarRequest(BaseModel):
    nev: str
    telszam: str
    jarmu: Jarmu
    hatosugar_km: int


class FutarModositRequest(FutarRequest):
    aktiv: bool = True


class FutarAllapotRequest(BaseModel):
    allapot: Literal["elerheto", "szunet"]


class FutarPozicioRequest(BaseModel):
    futar_id: int
    gps_x: float = Field(description="Szélesség fokban (pl. 47.4979)")
    gps_y: float = Field(description="Hosszúság fokban (pl. 19.0402)")
    cim: str


class AllergenRequest(BaseModel):
    nev: str


class TermekRequest(BaseModel):
    nev: str
    fogas: str
    ar: int
    tipus: Literal["etel", "ital"] = "etel"
    leiras: str | None = None
    elkeszitesi_ido: int | None = None
    prioritas: int = 0
    aktiv: bool = True
    allergen_ellenorizve: bool = False
    allergen_kodok: list[int] = Field(default_factory=list)


class TetelRequest(BaseModel):
    termek_id: int
    db: int = Field(default=1, ge=1)


class SzamlazasiAdatRequest(BaseModel):
    nev: str
    cim: str
    adoszam: str | None = None


class RendelesRequest(BaseModel):
    felhasznalo_id: int
    km: int = Field(gt=0)
    fizetesi_mod: Literal["keszpenz", "kartya"]
    tetelek: list[TetelRequest] = Field(min_length=1)
    cim: str | None = Field(default=None, description="Alapból a felhasználó címe")
    prioritas: int = Field(default=0, ge=0, le=1)
    szamla: int = Field(default=0, ge=0, le=1)
    szamlazasi_adat: SzamlazasiAdatRequest | None = Field(
        default=None, description="Alapból a felhasználó neve és címe (csak szamla=1 mellett)")


class FelhasznaloAzonositoRequest(BaseModel):
    felhasznalo_id: int


class TetelHozzaadRequest(FelhasznaloAzonositoRequest):
    termek_id: int
    db: int = Field(default=1, ge=1)


class TetelModositRequest(FelhasznaloAzonositoRequest):
    db: int = Field(ge=1)


class ErtekelesRequest(FelhasznaloAzonositoRequest):
    ertekeles: int = Field(ge=1, le=5)


class JattRequest(FelhasznaloAzonositoRequest):
    jatt: int = Field(gt=0)


class FutarAzonositoRequest(BaseModel):
    futar_id: int


# ---------------------------------------------------------------------------
# Válaszok
# ---------------------------------------------------------------------------
def _felhasznalo_adat(felhasznalo: Felhasznalo) -> dict:
    return {
        "id": felhasznalo.id,
        "nev": felhasznalo.nev,
        "cim": felhasznalo.cim,
        "telszam": felhasznalo.telszam,
        "email": felhasznalo.email,
        "admin": felhasznalo.admin,
        "aktiv": felhasznalo.aktiv,
    }


def _futar_adat(futar: Futar) -> dict:
    return {
        "id": futar.id,
        "nev": futar.nev,
        "telszam": futar.telszam,
        "jarmu": futar.jarmu,
        "allapot": futar.allapot,
        "hatosugar_km": futar.hatosugar_km,
        "aktiv": futar.aktiv,
    }


def _pozicio_adat(pozicio: FutarPozicio) -> dict:
    return {
        "id": pozicio.id,
        "futar_id": pozicio.futar_id,
        "gps_x": pozicio.gps_x,
        "gps_y": pozicio.gps_y,
        "cim": pozicio.cim,
        "frissitve": pozicio.frissitve,
    }


def _termek_adat(termek: Termek) -> dict:
    return {
        "id": termek.id,
        "tipus": termek.tipus,
        "nev": termek.nev,
        "fogas": termek.fogas,
        "leiras": termek.leiras,
        "ar": termek.ar,
        "elkeszitesi_ido": termek.elkeszitesi_ido,
        "prioritas": termek.prioritas,
        "aktiv": termek.aktiv,
        "allergen_ellenorizve": termek.allergen_ellenorizve,
        "allergenek": [
            {"kod": allergen.kod, "nev": allergen.nev}
            for allergen in termek.allergenek
        ],
    }


def _rendeles_adat(rendeles: Rendeles) -> dict:
    szamlazasi = rendeles.szamlazasi_adat
    return {
        "id": rendeles.id,
        "felhasznalo_id": rendeles.felhasznalo_id,
        "futar_id": rendeles.futar_id,
        "cim": rendeles.cim,
        "prioritas": rendeles.prioritas,
        "fizetesi_mod": rendeles.fizetesi_mod,
        "jatt": rendeles.jatt,
        "szamla": rendeles.szamla,
        "km": rendeles.km,
        "szallitasi_dij": rendeles.szallitasi_dij,
        "statusz": rendeles.statusz,
        "ertekeles": rendeles.ertekeles,
        "letrehozva": rendeles.letrehozva,
        "kiszallitva_ido": rendeles.kiszallitva_ido,
        "tetelek": [
            {
                "termek": _termek_adat(tetel.termek),
                "db": tetel.db,
                "egysegar": tetel.egysegar,
                "osszeg": tetel.osszeg(),
            }
            for tetel in rendeles.tetelek
        ],
        "szamlazasi_adat": {
            "nev": szamlazasi.nev, "cim": szamlazasi.cim, "adoszam": szamlazasi.adoszam,
        } if szamlazasi else None,
        "termek_osszeg": rendeles.termek_osszeg(),
        "vegosszeg": rendeles.vegosszeg(),
    }


Limit = Query(default=100, ge=1, le=1000)
Offset = Query(default=0, ge=0)


# ---------------------------------------------------------------------------
# Bejelentkezés és felhasználó
# ---------------------------------------------------------------------------
@app.post("/bejelentkezes")
def ep_bejelentkezes(body: BejelentkezesRequest):
    felhasznalo = adatbazis.bejelentkezes(body.email, body.jelszo)
    if felhasznalo is None:
        raise HTTPException(status_code=401, detail="Hibás e-mail-cím vagy jelszó.")
    return _felhasznalo_adat(felhasznalo)


@app.post("/felhasznalo", status_code=201)
def ep_felhasznalo_letrehoz(body: FelhasznaloRequest):
    felhasznalo = Felhasznalo.regisztral(
        body.nev, body.cim, body.telszam, body.email, body.jelszo, body.admin
    )
    adatbazis.felhasznalo_letrehoz(felhasznalo)
    return _felhasznalo_adat(felhasznalo)


@app.get("/felhasznalo")
def ep_felhasznalok_szur(
    nev_tartalmaz: str | None = None,
    cim_tartalmaz: str | None = None,
    telszam: str | None = None,
    email: str | None = None,
    email_tartalmaz: str | None = None,
    admin: bool | None = None,
    aktiv: bool | None = None,
    rendezes: str | None = None,
    csokkeno: bool = False,
    limit: int = Limit,
    offset: int = Offset,
):
    return [
        _felhasznalo_adat(f)
        for f in adatbazis.felhasznalok_szur(
            nev_tartalmaz=nev_tartalmaz,
            cim_tartalmaz=cim_tartalmaz,
            telszam=telszam,
            email=email,
            email_tartalmaz=email_tartalmaz,
            admin=admin,
            aktiv=aktiv,
            rendezes=rendezes,
            csokkeno=csokkeno,
            limit=limit,
            offset=offset,
        )
    ]


@app.get("/felhasznalo/email/{email}")
def ep_felhasznalo_lekerdez_emailre(email: str):
    return _felhasznalo_adat(
        _vagy_404(
            adatbazis.felhasznalo_lekerdez_emailre(email),
            "Felhasználó nem található",
        )
    )


@app.get("/felhasznalo/{felhasznalo_id}")
def ep_felhasznalo_lekerdez(felhasznalo_id: int):
    return _felhasznalo_adat(
        _vagy_404(
            adatbazis.felhasznalo_lekerdez(felhasznalo_id),
            "Felhasználó nem található",
        )
    )


@app.put("/felhasznalo/{felhasznalo_id}")
def ep_felhasznalo_modosit(felhasznalo_id: int, body: FelhasznaloModositRequest):
    regi = _vagy_404(adatbazis.felhasznalo_lekerdez(felhasznalo_id), "Felhasználó nem található")
    felhasznalo = Felhasznalo(
        id=felhasznalo_id, nev=body.nev, cim=body.cim, telszam=body.telszam, email=body.email,
        jelszo_hash=regi.jelszo_hash, admin=body.admin, aktiv=body.aktiv,
    )
    if body.jelszo is not None:
        felhasznalo.jelszo_beallit(body.jelszo)
    adatbazis.felhasznalo_modosit(felhasznalo)
    return _felhasznalo_adat(felhasznalo)


@app.delete("/felhasznalo/{felhasznalo_id}")
def ep_felhasznalo_inaktival(felhasznalo_id: int):
    """Nem töröl: inaktiválja a felhasználót, a rendelései megmaradnak."""
    if not adatbazis.felhasznalo_inaktival(felhasznalo_id):
        raise HTTPException(status_code=404, detail="Felhasználó nem található")
    return _felhasznalo_adat(adatbazis.felhasznalo_lekerdez(felhasznalo_id))


@app.get("/felhasznalo/{felhasznalo_id}/rendelesek")
def ep_felhasznalo_rendelesei(felhasznalo_id: int, limit: int = Limit, offset: int = Offset):
    return [
        _rendeles_adat(r)
        for r in adatbazis.rendelesek_szur(felhasznalo_id=felhasznalo_id, rendezes="letrehozva",
                                           csokkeno=True, limit=limit, offset=offset)
    ]


# ---------------------------------------------------------------------------
# Futár
# ---------------------------------------------------------------------------
@app.post("/futar/bejelentkezes")
def ep_futar_bejelentkezes(body: FutarBejelentkezesRequest):
    futar = adatbazis.futar_lekerdez_bejelentkezeshez(body.nev, body.telszam)
    if futar is None:
        raise HTTPException(status_code=401, detail="A futár nem található, vagy inaktív.")
    return _futar_adat(futar)


@app.post("/futar", status_code=201)
def ep_futar_letrehoz(body: FutarRequest):
    futar = Futar(nev=body.nev, telszam=body.telszam, jarmu=body.jarmu,
                  hatosugar_km=body.hatosugar_km)
    adatbazis.futar_letrehoz(futar)
    return _futar_adat(futar)


@app.get("/futar")
def ep_futarok_szur(
    jarmu: list[Jarmu] | None = Query(default=None),
    allapot: list[str] | None = Query(default=None),
    aktiv: bool | None = None,
    min_hatosugar_km: int | None = None,
    nev_tartalmaz: str | None = None,
    rendezes: str | None = None,
    csokkeno: bool = False,
    limit: int = Limit,
    offset: int = Offset,
):
    return [
        _futar_adat(f)
        for f in adatbazis.futarok_szur(
            jarmu=jarmu,
            allapot=allapot,
            aktiv=aktiv,
            min_hatosugar_km=min_hatosugar_km,
            nev_tartalmaz=nev_tartalmaz,
            rendezes=rendezes,
            csokkeno=csokkeno,
            limit=limit,
            offset=offset,
        )
    ]


@app.get("/futar/elerheto")
def ep_elerheto_futarok(jarmu: Jarmu | None = None):
    return [_futar_adat(f) for f in adatbazis.elerheto_futarok(jarmu)]


@app.get("/futar/allapotok")
def ep_futar_allapotok():
    megnevezesek = {
        "elerheto": "Elérhető",
        "uton": "Úton",
        "szunet": "Szünet",
    }
    return [
        {"ertek": allapot, "megnevezes": megnevezesek[allapot]}
        for allapot in FUTAR_ALLAPOTOK
    ]


@app.get("/futar/szallitasra-alkalmas")
def ep_szallitasra_alkalmas_futarok(km: int = Query(gt=0)):
    return [
        _futar_adat(f)
        for f in adatbazis.szallitasra_alkalmas_futarok(km)
    ]


@app.post("/futar/pozicio")
def ep_futar_pozicio_rogzit(body: FutarPozicioRequest):
    """A futár aktuális pozícióját írja felül (futáronként egy sor); csak úton lévő futár."""
    pozicio = FutarPozicio(futar_id=body.futar_id, gps_x=body.gps_x, gps_y=body.gps_y,
                           cim=body.cim)
    return _pozicio_adat(adatbazis.futar_pozicio_rogzit(pozicio))


@app.get("/futar/{futar_id}")
def ep_futar_lekerdez(futar_id: int):
    return _futar_adat(
        _vagy_404(adatbazis.futar_lekerdez(futar_id), "Futár nem található")
    )


@app.put("/futar/{futar_id}")
def ep_futar_modosit(futar_id: int, body: FutarModositRequest):
    regi = _vagy_404(adatbazis.futar_lekerdez(futar_id), "Futár nem található")
    futar = Futar(id=futar_id, nev=body.nev, telszam=body.telszam, jarmu=body.jarmu,
                  hatosugar_km=body.hatosugar_km, allapot=regi.allapot, aktiv=body.aktiv)
    adatbazis.futar_modosit(futar)
    return _futar_adat(adatbazis.futar_lekerdez(futar_id))


@app.delete("/futar/{futar_id}")
def ep_futar_inaktival(futar_id: int):
    """Nem töröl: inaktiválja a futárt, a rendelései megmaradnak."""
    adatbazis.futar_inaktival(futar_id)
    return _futar_adat(adatbazis.futar_lekerdez(futar_id))


@app.patch("/futar/{futar_id}/allapot")
def ep_futar_allapot_modosit(futar_id: int, body: FutarAllapotRequest):
    """Kézi váltás: elerheto <-> szunet. Az 'uton' a rendelés felvételével jár."""
    adatbazis.futar_allapot_valt(futar_id, body.allapot)
    return _futar_adat(adatbazis.futar_lekerdez(futar_id))


@app.get("/futar/{futar_id}/pozicio")
def ep_futar_pozicio(futar_id: int):
    _vagy_404(adatbazis.futar_lekerdez(futar_id), "Futár nem található")
    pozicio = adatbazis.futar_pozicio_lekerdez(futar_id)
    return _pozicio_adat(pozicio) if pozicio else None


@app.get("/futar/{futar_id}/rendelesek")
def ep_futar_rendelesei(futar_id: int, limit: int = Limit, offset: int = Offset):
    return [
        _rendeles_adat(r)
        for r in adatbazis.rendelesek_szur(futar_id=futar_id, rendezes="letrehozva",
                                           csokkeno=True, limit=limit, offset=offset)
    ]


@app.get("/futar/{futar_id}/felveheto-rendelesek")
def ep_futar_felveheto_rendelesek(futar_id: int, limit: int = Limit, offset: int = Offset):
    """Új, futár nélküli rendelések a futár hatósugarán belül, a prioritásosak elöl."""
    return [_rendeles_adat(r) for r in adatbazis.felveheto_rendelesek(futar_id, limit, offset)]


# ---------------------------------------------------------------------------
# Fogás és allergén
# ---------------------------------------------------------------------------
@app.get("/fogas")
def ep_fogasok():
    return [{"kod": f.kod, "tipus": f.tipus} for f in adatbazis.fogasok_lekerdez()]


@app.get("/allergen")
def ep_allergenek():
    return [{"kod": a.kod, "nev": a.nev} for a in adatbazis.allergenek_lekerdez()]


@app.post("/allergen", status_code=201)
def ep_allergen_letrehoz(body: AllergenRequest):
    allergen = Allergen(nev=body.nev)
    adatbazis.allergen_letrehoz(allergen)
    return {"kod": allergen.kod, "nev": allergen.nev}


@app.put("/allergen/{kod}")
def ep_allergen_modosit(kod: int, body: AllergenRequest):
    allergen = Allergen(nev=body.nev, kod=kod)
    if not adatbazis.allergen_modosit(allergen):
        raise HTTPException(status_code=404, detail="Allergén nem található")
    return {"kod": allergen.kod, "nev": allergen.nev}


@app.delete("/allergen/{kod}")
def ep_allergen_torol(kod: int):
    """Használatban lévő allergén nem törölhető (409)."""
    adatbazis.allergen_torol(kod)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Termék
# ---------------------------------------------------------------------------
def _termek_bodybol(body: TermekRequest, termek_id: int | None = None) -> Termek:
    return Termek(
        id=termek_id,
        nev=body.nev,
        fogas=body.fogas,
        ar=body.ar,
        tipus=body.tipus,
        leiras=body.leiras,
        elkeszitesi_ido=body.elkeszitesi_ido,
        prioritas=body.prioritas,
        aktiv=body.aktiv,
        allergen_ellenorizve=body.allergen_ellenorizve,
        allergenek=[Allergen(nev="?", kod=kod) for kod in dict.fromkeys(body.allergen_kodok)],
    )


@app.post("/termek", status_code=201)
def ep_termek_letrehoz(body: TermekRequest):
    termek_id = adatbazis.termek_letrehoz(_termek_bodybol(body))
    return _termek_adat(adatbazis.termek_lekerdez(termek_id))


@app.get("/termek")
def ep_termekek_szur(
    tipus: str | None = None,
    fogas: list[str] | None = Query(default=None),
    ar_min: int | None = None,
    ar_max: int | None = None,
    nev_tartalmaz: str | None = None,
    max_elkeszitesi_ido: int | None = None,
    prioritas: int | None = None,
    aktiv: bool | None = None,
    nem_tartalmaz_allergen: list[int] | None = Query(default=None),
    rendezes: str | None = None,
    csokkeno: bool = False,
    limit: int = Limit,
    offset: int = Offset,
):
    return [
        _termek_adat(t)
        for t in adatbazis.termekek_szur(
            tipus=tipus,
            fogas=fogas,
            ar_min=ar_min,
            ar_max=ar_max,
            nev_tartalmaz=nev_tartalmaz,
            max_elkeszitesi_ido=max_elkeszitesi_ido,
            prioritas=prioritas,
            aktiv=aktiv,
            nem_tartalmaz_allergen=nem_tartalmaz_allergen,
            rendezes=rendezes,
            csokkeno=csokkeno,
            limit=limit,
            offset=offset,
        )
    ]


@app.get("/termek/{termek_id}")
def ep_termek_lekerdez(termek_id: int):
    return _termek_adat(
        _vagy_404(adatbazis.termek_lekerdez(termek_id), "Termék nem található")
    )


@app.put("/termek/{termek_id}")
def ep_termek_modosit(termek_id: int, body: TermekRequest):
    """Az allergénlistát is lecseréli. Inaktiválás: aktiv = false."""
    if not adatbazis.termek_modosit(_termek_bodybol(body, termek_id)):
        raise HTTPException(status_code=404, detail="Termék nem található")
    return _termek_adat(adatbazis.termek_lekerdez(termek_id))


@app.delete("/termek/{termek_id}")
def ep_termek_torol(termek_id: int):
    """Rendelésben már szerepelt termék nem törölhető (409), csak inaktiválható."""
    adatbazis.termek_torol(termek_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Rendelés
# ---------------------------------------------------------------------------
@app.post("/rendeles", status_code=201)
def ep_rendeles_letrehoz(body: RendelesRequest):
    """Új rendelés 'új' státusszal, futár nélkül. Jatt és értékelés a kiszállítás után adható."""
    szamlazasi = (SzamlazasiAdat(body.szamlazasi_adat.nev, body.szamlazasi_adat.cim,
                                 body.szamlazasi_adat.adoszam)
                  if body.szamlazasi_adat else None)
    rendeles = adatbazis.rendeles_letrehoz(
        body.felhasznalo_id,
        km=body.km,
        fizetesi_mod=body.fizetesi_mod,
        tetelek=[(t.termek_id, t.db) for t in body.tetelek],
        cim=body.cim,
        prioritas=body.prioritas,
        szamla=body.szamla,
        szamlazasi_adat=szamlazasi,
    )
    return _rendeles_adat(rendeles)


@app.get("/rendeles/statuszok")
def ep_rendeles_statuszok():
    return list(RENDELES_STATUSZOK)


@app.get("/rendeles")
def ep_rendelesek_szur(
    felhasznalo_id: int | None = None,
    futar_id: int | None = None,
    statusz: list[str] | None = Query(default=None),
    fizetesi_mod: str | None = None,
    prioritas: int | None = None,
    szamla: int | None = None,
    km_min: int | None = None,
    km_max: int | None = None,
    ertekeles_min: int | None = None,
    ertekeles_max: int | None = None,
    van_jatt: bool | None = None,
    cim_tartalmaz: str | None = None,
    termek_id: int | None = None,
    letrehozva_tol: str | None = None,
    letrehozva_ig: str | None = None,
    rendezes: str | None = None,
    csokkeno: bool = False,
    limit: int = Limit,
    offset: int = Offset,
):
    return [
        _rendeles_adat(r)
        for r in adatbazis.rendelesek_szur(
            felhasznalo_id=felhasznalo_id,
            futar_id=futar_id,
            statusz=statusz,
            fizetesi_mod=fizetesi_mod,
            prioritas=prioritas,
            szamla=szamla,
            km_min=km_min,
            km_max=km_max,
            ertekeles_min=ertekeles_min,
            ertekeles_max=ertekeles_max,
            van_jatt=van_jatt,
            cim_tartalmaz=cim_tartalmaz,
            termek_id=termek_id,
            letrehozva_tol=letrehozva_tol,
            letrehozva_ig=letrehozva_ig,
            rendezes=rendezes,
            csokkeno=csokkeno,
            limit=limit,
            offset=offset,
        )
    ]


@app.get("/rendeles/{rendeles_id}")
def ep_rendeles_lekerdez(rendeles_id: int):
    return _rendeles_adat(
        _vagy_404(
            adatbazis.rendeles_lekerdez(rendeles_id),
            "Rendelés nem található",
        )
    )


@app.get("/rendeles/{rendeles_id}/allergenek")
def ep_rendeles_allergenek(rendeles_id: int):
    rendeles = _vagy_404(
        adatbazis.rendeles_lekerdez(rendeles_id),
        "Rendelés nem található",
    )
    return {
        "rendeles_id": rendeles.id,
        "allergenek": sorted(rendeles.allergenek()),
    }


# --- a megrendelő műveletei (felhasznalo_id: a kérést küldő felhasználó) ---
@app.post("/rendeles/{rendeles_id}/tetelek")
def ep_tetel_hozzaad(rendeles_id: int, body: TetelHozzaadRequest):
    """Csak új státuszban; ugyanaz a termék újra: a darabszám nő."""
    return _rendeles_adat(adatbazis.tetel_hozzaad(rendeles_id, body.felhasznalo_id,
                                                  body.termek_id, body.db))


@app.patch("/rendeles/{rendeles_id}/tetelek/{termek_id}")
def ep_tetel_modosit(rendeles_id: int, termek_id: int, body: TetelModositRequest):
    return _rendeles_adat(adatbazis.tetel_modosit(rendeles_id, body.felhasznalo_id,
                                                  termek_id, body.db))


@app.delete("/rendeles/{rendeles_id}/tetelek/{termek_id}")
def ep_tetel_torol(rendeles_id: int, termek_id: int, felhasznalo_id: int = Query()):
    """Az utolsó tétel nem törölhető (409): helyette a rendelést kell lemondani."""
    return _rendeles_adat(adatbazis.tetel_torol(rendeles_id, felhasznalo_id, termek_id))


@app.post("/rendeles/{rendeles_id}/lemondas")
def ep_rendeles_lemond(rendeles_id: int, body: FelhasznaloAzonositoRequest):
    return _rendeles_adat(adatbazis.rendeles_lemond(rendeles_id, body.felhasznalo_id))


@app.post("/rendeles/{rendeles_id}/ertekeles")
def ep_rendeles_ertekel(rendeles_id: int, body: ErtekelesRequest):
    return _rendeles_adat(adatbazis.rendeles_ertekel(rendeles_id, body.felhasznalo_id,
                                                     body.ertekeles))


@app.post("/rendeles/{rendeles_id}/jatt")
def ep_rendeles_jatt(rendeles_id: int, body: JattRequest):
    return _rendeles_adat(adatbazis.rendeles_jatt(rendeles_id, body.felhasznalo_id, body.jatt))


# --- futár és konyha: új -> elfogadva -> készül -> úton -> kiszállítva ---
@app.post("/rendeles/{rendeles_id}/felvetel")
def ep_rendeles_felvesz(rendeles_id: int, body: FutarAzonositoRequest):
    """A futár felveszi a rendelést; a futár 'uton' állapotba kerül."""
    return _rendeles_adat(adatbazis.rendeles_felvesz(rendeles_id, body.futar_id))


@app.post("/rendeles/{rendeles_id}/keszul")
def ep_rendeles_keszul(rendeles_id: int):
    """A konyha jelzi, hogy készíti a rendelést."""
    return _rendeles_adat(adatbazis.rendeles_keszul(rendeles_id))


@app.post("/rendeles/{rendeles_id}/atvetel")
def ep_rendeles_atvesz(rendeles_id: int, body: FutarAzonositoRequest):
    return _rendeles_adat(adatbazis.rendeles_atvesz(rendeles_id, body.futar_id))


@app.post("/rendeles/{rendeles_id}/kiszallitas")
def ep_rendeles_kiszallit(rendeles_id: int, body: FutarAzonositoRequest):
    """A futár újra elérhető lesz; a kiszállítás idejét az adatbázis rögzíti."""
    return _rendeles_adat(adatbazis.rendeles_kiszallit(rendeles_id, body.futar_id))
