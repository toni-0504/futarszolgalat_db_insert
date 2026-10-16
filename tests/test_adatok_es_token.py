import pytest


@pytest.mark.parametrize("utvonal", ["/felhasznalo", "/futar", "/termek", "/rendeles"])
def test_a_meglevo_adatok_mind_betolthetok(kliens, utvonal):
    """A modellek validációja a végleges adatbázis minden sorát elfogadja."""
    offset, osszes = 0, 0
    while True:
        valasz = kliens.get(utvonal, params={"limit": 1000, "offset": offset})
        assert valasz.status_code == 200, valasz.text
        osszes += len(valasz.json())
        if len(valasz.json()) < 1000:
            break
        offset += 1000
    assert osszes > 0


def test_a_poziciok_fokban_vannak(kliens):
    p = kliens.get("/futar/1/pozicio").json()
    assert 47 < p["gps_x"] < 48 and 18 < p["gps_y"] < 20 and p["frissitve"]


def test_api_token_az_iro_kerelseknel(kliens, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "titok")
    uj = {"nev": "Allergén X"}
    assert kliens.post("/allergen", json=uj).status_code == 401
    assert kliens.post("/allergen", json=uj, headers={"Authorization": "Bearer rossz"}).status_code == 401
    assert kliens.post("/allergen", json=uj, headers={"Authorization": "Bearer titok"}).status_code == 201
    assert kliens.get("/allergen").status_code == 200
