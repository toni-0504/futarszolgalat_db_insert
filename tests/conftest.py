"""Minden teszt a repó adatbázisának egy ideiglenes másolatán fut."""
import shutil
from itertools import count
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ALAP_DB = Path(__file__).resolve().parent.parent / "futarszolgalat.db"
_sorszam = count(1)


@pytest.fixture
def kliens(tmp_path, monkeypatch):
    db = tmp_path / "teszt.db"
    shutil.copy(ALAP_DB, db)
    monkeypatch.setenv("FUTARSZOLGALAT_DB", str(db))
    monkeypatch.delenv("API_TOKEN", raising=False)
    import api
    return TestClient(api.app)


@pytest.fixture
def felhasznalo(kliens):
    """Új, aktív felhasználó; a jelszava 'titkos123'."""
    def letrehoz(**adat) -> dict:
        n = next(_sorszam)
        alap = {"nev": f"Teszt Elek {n}", "cim": "Budapest, Fő utca 1.",
                "telszam": f"+3630{n:07d}", "email": f"teszt{n}@example.com",
                "jelszo": "titkos123"}
        valasz = kliens.post("/felhasznalo", json={**alap, **adat})
        assert valasz.status_code == 201, valasz.text
        return valasz.json()
    return letrehoz


@pytest.fixture
def futar(kliens):
    """Új, elérhető autós futár 20 km hatósugárral."""
    def letrehoz(**adat) -> dict:
        n = next(_sorszam)
        alap = {"nev": f"Futár {n}", "telszam": f"+3620{n:07d}", "jarmu": "auto", "hatosugar_km": 20}
        valasz = kliens.post("/futar", json={**alap, **adat})
        assert valasz.status_code == 201, valasz.text
        return valasz.json()
    return letrehoz


@pytest.fixture
def termek(kliens):
    """Új, aktív étel ('foetel' fogás)."""
    def letrehoz(**adat) -> dict:
        n = next(_sorszam)
        alap = {"nev": f"Teszt étel {n}", "fogas": "foetel", "ar": 2000, "elkeszitesi_ido": 15}
        valasz = kliens.post("/termek", json={**alap, **adat})
        assert valasz.status_code == 201, valasz.text
        return valasz.json()
    return letrehoz


@pytest.fixture
def rendeles(kliens, felhasznalo, termek):
    """Új rendelés egy tétellel; visszaadja a rendelést és a megrendelőt."""
    def letrehoz(felh: dict | None = None, **adat) -> tuple[dict, dict]:
        felh = felh or felhasznalo()
        alap = {"felhasznalo_id": felh["id"], "km": 5, "fizetesi_mod": "kartya",
                "tetelek": [{"termek_id": termek()["id"], "db": 1}]}
        valasz = kliens.post("/rendeles", json={**alap, **adat})
        assert valasz.status_code == 201, valasz.text
        return valasz.json(), felh
    return letrehoz
