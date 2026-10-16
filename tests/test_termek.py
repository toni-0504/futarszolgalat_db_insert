def test_fogas_es_tipus_parosnak_leteznie_kell(kliens, termek):
    assert {"kod": "hideg_ital", "tipus": "ital"} in kliens.get("/fogas").json()
    alap = {"nev": "Kóla", "ar": 500, "tipus": "ital"}
    assert kliens.post("/termek", json={**alap, "fogas": "foetel"}).status_code == 400
    assert kliens.post("/termek", json={**alap, "fogas": "nincs_ilyen"}).status_code == 400
    assert kliens.post("/termek", json={**alap, "fogas": "hideg_ital"}).status_code == 201


def test_etelnel_az_elkeszitesi_ido_kotelezo(kliens):
    assert kliens.post("/termek", json={"nev": "Leves", "fogas": "leves", "ar": 900}).status_code == 400


def test_allergenek_es_modositas(kliens, termek):
    t = termek(allergen_kodok=[1, 2])
    assert [a["kod"] for a in t["allergenek"]] == [1, 2]
    assert kliens.post("/termek", json={"nev": "X", "fogas": "foetel", "ar": 1, "elkeszitesi_ido": 5,
                                        "allergen_kodok": [999]}).status_code == 404
    valasz = kliens.put(f"/termek/{t['id']}", json={"nev": t["nev"], "fogas": "foetel", "ar": 2500,
                                                    "elkeszitesi_ido": 15, "allergen_kodok": [3],
                                                    "allergen_ellenorizve": True})
    assert valasz.json()["ar"] == 2500 and [a["kod"] for a in valasz.json()["allergenek"]] == [3]
    assert valasz.json()["allergen_ellenorizve"] is True


def test_rendelt_termek_nem_torolheto_csak_inaktivalhato(kliens, termek, rendeles):
    r, _ = rendeles()
    termek_id = r["tetelek"][0]["termek"]["id"]
    assert kliens.delete(f"/termek/{termek_id}").status_code == 409
    t = kliens.get(f"/termek/{termek_id}").json()
    inaktiv = kliens.put(f"/termek/{termek_id}", json={**t, "aktiv": False, "allergen_kodok": []}).json()
    assert inaktiv["aktiv"] is False
    assert termek_id not in [x["id"] for x in kliens.get("/termek", params={"aktiv": True, "limit": 1000,
                                                                            "nev_tartalmaz": "Teszt étel"}).json()]

    uj = termek()
    assert kliens.delete(f"/termek/{uj['id']}").status_code == 200
    assert kliens.get(f"/termek/{uj['id']}").status_code == 404


def test_allergen_kezeles(kliens, termek):
    uj = kliens.post("/allergen", json={"nev": "Csillagánizs"}).json()
    assert kliens.post("/allergen", json={"nev": "CSILLAGÁNIZS"}).status_code in (409,)
    assert kliens.put(f"/allergen/{uj['kod']}", json={"nev": "Ánizs"}).json()["nev"] == "Ánizs"
    termek(allergen_kodok=[uj["kod"]])
    assert kliens.delete(f"/allergen/{uj['kod']}").status_code == 409
    szabad = kliens.post("/allergen", json={"nev": "Próba allergén"}).json()
    assert kliens.delete(f"/allergen/{szabad['kod']}").status_code == 200
