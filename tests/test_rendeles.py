def test_rendeles_leadasa(kliens, felhasznalo, termek):
    f = felhasznalo(cim="Budapest, Fő utca 1.")
    leves = termek(ar=2400)
    ital = kliens.post("/termek", json={"nev": "Ásványvíz", "fogas": "hideg_ital", "tipus": "ital", "ar": 600}).json()
    valasz = kliens.post("/rendeles", json={
        "felhasznalo_id": f["id"], "km": 4, "fizetesi_mod": "kartya", "szamla": 1,
        "szamlazasi_adat": {"nev": "Teszt Kft.", "cim": "Budapest, Ipar utca 3.", "adoszam": "12345678-1-42"},
        "tetelek": [{"termek_id": leves["id"], "db": 1}, {"termek_id": ital["id"], "db": 2},
                    {"termek_id": leves["id"], "db": 1}],
    })
    assert valasz.status_code == 201, valasz.text
    r = valasz.json()
    assert r["statusz"] == "új" and r["futar_id"] is None and r["ertekeles"] is None and r["jatt"] is None
    assert r["cim"] == "Budapest, Fő utca 1." and r["letrehozva"]
    assert [(t["termek"]["id"], t["db"], t["egysegar"]) for t in r["tetelek"]] == [(leves["id"], 2, 2400), (ital["id"], 2, 600)]
    assert r["termek_osszeg"] == 6000 and r["szamlazasi_adat"]["adoszam"] == "12345678-1-42"

    kliens.put(f"/termek/{leves['id']}", json={"nev": leves["nev"], "fogas": "foetel", "ar": 9999, "elkeszitesi_ido": 15})
    assert kliens.get(f"/rendeles/{r['id']}").json()["tetelek"][0]["egysegar"] == 2400


def test_szamla_alapbol_a_felhasznalo_adataival(kliens, rendeles, felhasznalo):
    f = felhasznalo(nev="Számla Béla")
    r, _ = rendeles(f, szamla=1)
    assert r["szamlazasi_adat"] == {"nev": "Számla Béla", "cim": f["cim"], "adoszam": None}
    assert rendeles(f)[0]["szamlazasi_adat"] is None


def test_ervenytelen_rendelesek(kliens, felhasznalo, termek):
    f = felhasznalo()
    alap = {"felhasznalo_id": f["id"], "km": 4, "fizetesi_mod": "kartya"}
    assert kliens.post("/rendeles", json={**alap, "tetelek": []}).status_code == 422
    inaktiv = termek(aktiv=False)
    assert kliens.post("/rendeles", json={**alap, "tetelek": [{"termek_id": inaktiv["id"]}]}).status_code == 409
    jo = termek()
    assert kliens.post("/rendeles", json={**alap, "szamlazasi_adat": {"nev": "X", "cim": "Y"},
                                          "tetelek": [{"termek_id": jo["id"]}]}).status_code == 400
    assert kliens.post("/rendeles", json={**alap, "szamla": 1, "szamlazasi_adat": {"nev": "X", "cim": "Y", "adoszam": "123"},
                                          "tetelek": [{"termek_id": jo["id"]}]}).status_code == 400
    assert kliens.post("/rendeles", json={**alap, "felhasznalo_id": 999999, "tetelek": [{"termek_id": jo["id"]}]}).status_code == 404


def test_teljes_folyamat(kliens, futar, rendeles):
    f = futar()
    r, megrendelo = rendeles()
    rid = r["id"]

    felvett = kliens.post(f"/rendeles/{rid}/felvetel", json={"futar_id": f["id"]}).json()
    assert felvett["statusz"] == "elfogadva" and felvett["futar_id"] == f["id"]
    assert kliens.get(f"/futar/{f['id']}").json()["allapot"] == "uton"
    assert kliens.post(f"/rendeles/{rid}/keszul").json()["statusz"] == "készül"
    assert kliens.post(f"/rendeles/{rid}/atvetel", json={"futar_id": f["id"]}).json()["statusz"] == "úton"
    kiszallitott = kliens.post(f"/rendeles/{rid}/kiszallitas", json={"futar_id": f["id"]}).json()
    assert kiszallitott["statusz"] == "kiszállítva" and kiszallitott["kiszallitva_ido"]
    assert kliens.get(f"/futar/{f['id']}").json()["allapot"] == "elerheto"

    ertekelt = kliens.post(f"/rendeles/{rid}/ertekeles", json={"felhasznalo_id": megrendelo["id"], "ertekeles": 5})
    assert ertekelt.json()["ertekeles"] == 5
    assert kliens.post(f"/rendeles/{rid}/ertekeles", json={"felhasznalo_id": megrendelo["id"], "ertekeles": 1}).status_code == 409
    jatt = kliens.post(f"/rendeles/{rid}/jatt", json={"felhasznalo_id": megrendelo["id"], "jatt": 500}).json()
    assert jatt["jatt"] == 500 and jatt["vegosszeg"] == jatt["termek_osszeg"] + 500
    assert kliens.post(f"/rendeles/{rid}/jatt", json={"felhasznalo_id": megrendelo["id"], "jatt": 100}).status_code == 409


def test_keszul_nelkul_is_atveheto(kliens, futar, rendeles):
    f = futar()
    r, _ = rendeles()
    kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": f["id"]})
    assert kliens.post(f"/rendeles/{r['id']}/atvetel", json={"futar_id": f["id"]}).json()["statusz"] == "úton"


def test_egy_rendelest_csak_egy_futar_vehet_fel(kliens, futar, rendeles):
    elso, masodik = futar(), futar()
    r, _ = rendeles()
    assert kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": elso["id"]}).status_code == 200
    assert kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": masodik["id"]}).status_code == 409
    assert kliens.get(f"/futar/{masodik['id']}").json()["allapot"] == "elerheto"


def test_egy_futarnak_egy_aktiv_rendelese_lehet(kliens, futar, rendeles):
    f = futar()
    r1, _ = rendeles()
    r2, _ = rendeles()
    kliens.post(f"/rendeles/{r1['id']}/felvetel", json={"futar_id": f["id"]})
    assert kliens.post(f"/rendeles/{r2['id']}/felvetel", json={"futar_id": f["id"]}).status_code == 409
    assert kliens.get(f"/rendeles/{r2['id']}").json()["statusz"] == "új"


def test_hatosugar_szunet_es_inaktiv_futar(kliens, futar, rendeles):
    r, _ = rendeles(km=8)
    kozeli = futar(hatosugar_km=5)
    assert kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": kozeli["id"]}).status_code == 409
    assert kliens.get(f"/futar/{kozeli['id']}").json()["allapot"] == "elerheto"

    szunetelo = futar()
    kliens.patch(f"/futar/{szunetelo['id']}/allapot", json={"allapot": "szunet"})
    assert kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": szunetelo["id"]}).status_code == 409

    inaktiv = futar()
    kliens.delete(f"/futar/{inaktiv['id']}")
    assert kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": inaktiv["id"]}).status_code == 409


def test_mas_futar_nem_szallithatja_ki(kliens, futar, rendeles):
    f, masik = futar(), futar()
    r, _ = rendeles()
    kliens.post(f"/rendeles/{r['id']}/felvetel", json={"futar_id": f["id"]})
    kliens.post(f"/rendeles/{r['id']}/atvetel", json={"futar_id": f["id"]})
    assert kliens.post(f"/rendeles/{r['id']}/kiszallitas", json={"futar_id": masik["id"]}).status_code == 409


def test_lemondas(kliens, futar, rendeles, felhasznalo):
    r, megrendelo = rendeles()
    idegen = felhasznalo()
    assert kliens.post(f"/rendeles/{r['id']}/lemondas", json={"felhasznalo_id": idegen["id"]}).status_code == 403
    assert kliens.post(f"/rendeles/{r['id']}/lemondas", json={"felhasznalo_id": megrendelo["id"]}).json()["statusz"] == "lemondva"

    felvett, megrendelo2 = rendeles()
    kliens.post(f"/rendeles/{felvett['id']}/felvetel", json={"futar_id": futar()["id"]})
    assert kliens.post(f"/rendeles/{felvett['id']}/lemondas", json={"felhasznalo_id": megrendelo2["id"]}).status_code == 409


def test_ertekeles_es_jatt_szabalyai(kliens, futar, rendeles):
    r, megrendelo = rendeles(fizetesi_mod="keszpenz")
    assert kliens.post(f"/rendeles/{r['id']}/ertekeles", json={"felhasznalo_id": megrendelo["id"], "ertekeles": 4}).status_code == 409
    assert kliens.post(f"/rendeles/{r['id']}/ertekeles", json={"felhasznalo_id": megrendelo["id"], "ertekeles": 6}).status_code == 422
    f = futar()
    for lepes in ("felvetel", "atvetel", "kiszallitas"):
        kliens.post(f"/rendeles/{r['id']}/{lepes}", json={"futar_id": f["id"]})
    assert kliens.post(f"/rendeles/{r['id']}/jatt", json={"felhasznalo_id": megrendelo["id"], "jatt": 300}).status_code == 409


def test_tetelek_kezelese(kliens, rendeles, termek, felhasznalo):
    r, megrendelo = rendeles()
    elso = r["tetelek"][0]["termek"]["id"]
    masodik = termek()["id"]
    fid = megrendelo["id"]

    assert kliens.delete(f"/rendeles/{r['id']}/tetelek/{elso}", params={"felhasznalo_id": fid}).status_code == 409
    noveles = kliens.post(f"/rendeles/{r['id']}/tetelek", json={"felhasznalo_id": fid, "termek_id": elso, "db": 2}).json()
    assert noveles["tetelek"][0]["db"] == 3
    kliens.post(f"/rendeles/{r['id']}/tetelek", json={"felhasznalo_id": fid, "termek_id": masodik})
    assert kliens.patch(f"/rendeles/{r['id']}/tetelek/{masodik}", json={"felhasznalo_id": fid, "db": 4}).json()["tetelek"][1]["db"] == 4
    maradt = kliens.delete(f"/rendeles/{r['id']}/tetelek/{elso}", params={"felhasznalo_id": fid}).json()
    assert [t["termek"]["id"] for t in maradt["tetelek"]] == [masodik]

    idegen = felhasznalo()
    assert kliens.post(f"/rendeles/{r['id']}/tetelek", json={"felhasznalo_id": idegen["id"], "termek_id": elso}).status_code == 403
    kliens.post(f"/rendeles/{r['id']}/lemondas", json={"felhasznalo_id": fid})
    assert kliens.patch(f"/rendeles/{r['id']}/tetelek/{masodik}", json={"felhasznalo_id": fid, "db": 1}).status_code == 409


def test_felveheto_rendelesek_prioritas_szerint_a_hatosugaron_belul(kliens, futar, rendeles):
    f = futar(hatosugar_km=10)
    normal, _ = rendeles(km=3)
    prioritasos, _ = rendeles(km=3, prioritas=1)
    tavoli, _ = rendeles(km=30)
    idk = [x["id"] for x in kliens.get(f"/futar/{f['id']}/felveheto-rendelesek", params={"limit": 1000}).json()]
    assert tavoli["id"] not in idk
    assert idk.index(prioritasos["id"]) < idk.index(normal["id"])
    assert all(x["statusz"] == "új" and x["futar_id"] is None
               for x in kliens.get(f"/futar/{f['id']}/felveheto-rendelesek").json())


def test_szurok(kliens, rendeles):
    r, f = rendeles()
    sajat = kliens.get(f"/felhasznalo/{f['id']}/rendelesek").json()
    assert [x["id"] for x in sajat] == [r["id"]]
    datum = r["letrehozva"][:10]
    talalat = kliens.get("/rendeles", params={"letrehozva_tol": datum, "letrehozva_ig": datum, "limit": 1000}).json()
    assert r["id"] in [x["id"] for x in talalat]
    assert kliens.get("/rendeles", params={"rendezes": "jelszo"}).status_code == 400
    assert "kosar" in kliens.get("/rendeles/statuszok").json()


def test_inaktiv_termek_mennyisege_csak_csokkenhet(kliens, rendeles):
    r, f = rendeles()
    termek = r["tetelek"][0]["termek"]
    url = f"/rendeles/{r['id']}/tetelek/{termek['id']}"
    assert kliens.patch(url, json={"felhasznalo_id": f["id"], "db": 3}).status_code == 200
    kliens.put(f"/termek/{termek['id']}", json={"nev": termek["nev"], "fogas": "foetel", "ar": termek["ar"],
                                                "elkeszitesi_ido": 15, "aktiv": False})
    assert kliens.patch(url, json={"felhasznalo_id": f["id"], "db": 5}).status_code == 409
    assert kliens.patch(url, json={"felhasznalo_id": f["id"], "db": 1}).status_code == 200


def test_inaktiv_felhasznalo_nem_modosithatja_a_rendeleset(kliens, rendeles):
    r, f = rendeles()
    kliens.delete(f"/felhasznalo/{f['id']}")
    assert kliens.post(f"/rendeles/{r['id']}/lemondas", json={"felhasznalo_id": f["id"]}).status_code == 403
