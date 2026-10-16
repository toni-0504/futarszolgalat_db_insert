def test_futar_letrehozas_es_bejelentkezes(kliens, futar):
    f = futar(nev="Kovács Béla", telszam="+36201231234")
    assert f["allapot"] == "elerheto" and f["aktiv"] is True and "ember" not in f
    assert kliens.post("/futar/bejelentkezes", json={"nev": "Kovács Béla", "telszam": "+36201231234"}).status_code == 200
    assert kliens.post("/futar/bejelentkezes", json={"nev": "Kovács Béla", "telszam": "+36209999999"}).status_code == 401


def test_nincs_dron(kliens):
    valasz = kliens.post("/futar", json={"nev": "Drón", "telszam": "+36201112233", "jarmu": "dron", "hatosugar_km": 8})
    assert valasz.status_code == 422


def test_allapotvaltas_szabalyai(kliens, futar):
    f = futar()
    assert kliens.patch(f"/futar/{f['id']}/allapot", json={"allapot": "szunet"}).json()["allapot"] == "szunet"
    assert kliens.patch(f"/futar/{f['id']}/allapot", json={"allapot": "szunet"}).status_code == 409
    assert kliens.patch(f"/futar/{f['id']}/allapot", json={"allapot": "elerheto"}).json()["allapot"] == "elerheto"
    assert kliens.patch(f"/futar/{f['id']}/allapot", json={"allapot": "uton"}).status_code == 422


def test_uton_levo_futar_nem_mehet_szunetre_es_nem_inaktivalhato(kliens, futar, rendeles):
    f = futar()
    r, _ = rendeles()
    assert kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": f["id"]}).status_code == 200
    assert kliens.patch(f"/futar/{f['id']}/allapot", json={"allapot": "szunet"}).status_code == 409
    assert kliens.delete(f"/futar/{f['id']}").status_code == 409


def test_inaktivalas_es_modositas(kliens, futar):
    f = futar()
    valasz = kliens.put(f"/futar/{f['id']}", json={"nev": f["nev"], "telszam": f["telszam"],
                                                   "jarmu": "motor", "hatosugar_km": 25})
    assert valasz.json()["jarmu"] == "motor" and valasz.json()["allapot"] == "elerheto"
    assert kliens.delete(f"/futar/{f['id']}").json()["aktiv"] is False
    assert kliens.post("/futar/bejelentkezes", json={"nev": f["nev"], "telszam": f["telszam"]}).status_code == 401
    assert f["id"] not in [x["id"] for x in kliens.get("/futar/elerheto").json()]


def test_pozicio_csak_uton_futartol_es_futaronkent_egy_sor(kliens, futar, rendeles):
    f = futar()
    pozicio = {"futar_id": f["id"], "gps_x": 47.4979, "gps_y": 19.0402, "cim": "Budapest, Deák Ferenc tér"}
    assert kliens.post("/futar/pozicio", json=pozicio).status_code == 409
    assert kliens.get(f"/futar/{f['id']}/pozicio").json() is None

    r, _ = rendeles()
    kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": f["id"]})
    elso = kliens.post("/futar/pozicio", json=pozicio).json()
    masodik = kliens.post("/futar/pozicio", json={**pozicio, "gps_x": 47.5, "cim": "Budapest, Oktogon"}).json()
    assert masodik["id"] == elso["id"] and masodik["frissitve"]
    assert kliens.get(f"/futar/{f['id']}/pozicio").json()["cim"] == "Budapest, Oktogon"
    assert kliens.post("/futar/pozicio", json={**pozicio, "gps_x": 474979}).status_code == 400


def test_szallitasra_alkalmas_futarok(kliens, futar):
    kozeli = futar(hatosugar_km=3)
    tavoli = futar(hatosugar_km=40)
    idk = [x["id"] for x in kliens.get("/futar/szallitasra-alkalmas", params={"km": 10}).json()]
    assert tavoli["id"] in idk and kozeli["id"] not in idk
