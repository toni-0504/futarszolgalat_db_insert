def test_regisztracio_es_bejelentkezes(kliens, felhasznalo):
    f = felhasznalo(email="Valaki@Example.com")
    assert f["email"] == "valaki@example.com"
    assert "jelszo" not in f and "password" not in f

    assert kliens.post("/bejelentkezes", json={"email": "valaki@example.com", "jelszo": "titkos123"}).status_code == 200
    assert kliens.post("/bejelentkezes", json={"email": "valaki@example.com", "jelszo": "rossz-jelszo"}).status_code == 401


def test_jelszo_bcrypt_hashkent_tarolodik_laravel_kompatibilis_elotaggal(kliens, felhasznalo):
    import adatbazis
    f = felhasznalo()
    tarolt = adatbazis.felhasznalo_lekerdez(f["id"]).jelszo_hash
    assert tarolt.startswith("$2y$") and "titkos123" not in tarolt


def test_az_adatbazis_meglevo_hash_jei_ellenorizhetok(kliens):
    import adatbazis
    felhasznalok = adatbazis.felhasznalok_szur()
    assert felhasznalok and all(f.jelszo_hash.startswith("$2y$") for f in felhasznalok)


def test_email_egyedi_kis_es_nagybetutol_fuggetlenul(kliens, felhasznalo):
    felhasznalo(email="dupla@example.com")
    valasz = kliens.post("/felhasznalo", json={"nev": "Más", "cim": "Budapest", "telszam": "+36301112299",
                                               "email": "DUPLA@example.com", "jelszo": "titkos123"})
    assert valasz.status_code == 409


def test_telefonszam_es_jelszo_ellenorzes(kliens):
    alap = {"nev": "Teszt", "cim": "Budapest", "email": "x@example.com", "jelszo": "titkos123"}
    assert kliens.post("/felhasznalo", json={**alap, "telszam": "30 123 4567"}).status_code == 400
    assert kliens.post("/felhasznalo", json={**alap, "telszam": "+36301234567", "jelszo": "rovid"}).status_code == 400


def test_modositas_jelszo_nelkul_megtartja_a_jelszot(kliens, felhasznalo):
    f = felhasznalo()
    valasz = kliens.put(f"/felhasznalo/{f['id']}", json={**{k: f[k] for k in ("nev", "telszam", "email")},
                                                          "cim": "Debrecen, Piac utca 2."})
    assert valasz.status_code == 200 and valasz.json()["cim"] == "Debrecen, Piac utca 2."
    assert kliens.post("/bejelentkezes", json={"email": f["email"], "jelszo": "titkos123"}).status_code == 200


def test_torles_inaktival_es_a_rendelesek_megmaradnak(kliens, rendeles):
    r, f = rendeles()
    valasz = kliens.delete(f"/felhasznalo/{f['id']}")
    assert valasz.status_code == 200 and valasz.json()["aktiv"] is False
    assert kliens.get(f"/rendeles/{r['id']}").status_code == 200
    assert kliens.post("/bejelentkezes", json={"email": f["email"], "jelszo": "titkos123"}).status_code == 401
    uj = kliens.post("/rendeles", json={"felhasznalo_id": f["id"], "km": 3, "fizetesi_mod": "kartya",
                                        "tetelek": [{"termek_id": r["tetelek"][0]["termek"]["id"]}]})
    assert uj.status_code == 409
