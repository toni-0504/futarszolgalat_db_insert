# Futárszolgálat-adatbázis: repóáttekintés

## A projekt célja

A repó a futárszolgálat Python-alapú REST API-ja. A SQLite-adatbázisban
felhasználókat, futárokat, futárpozíciókat, termékeket, allergéneket és
rendeléseket kezel, és az üzleti folyamatokat (rendelésleadás, futárfelvétel,
kiszállítás, értékelés, jatt) is ez a réteg tartja be. Az üzleti objektumokat a
modellréteg írja le, az adatbázis-műveleteket az adatkezelő modul végzi, a
HTTP-s felületet pedig egy FastAPI-alkalmazás adja. A Laravel backend ezt az
API-t hívja HTTP-n.

## Fájlszerkezet

| Fájl | Szerep |
| --- | --- |
| `modellek.py` | Az üzleti objektumok, adatellenőrzések és néhány üzleti szabály. |
| `adatbazis.py` | Kapcsolódás a meglévő SQLite-adatbázishoz, a modellek mentése, betöltése, módosítása, inaktiválása és szűrése, valamint a rendelési folyamat lépései. Nem hoz létre és nem migrál sémát. |
| `api.py` | FastAPI-alkalmazás, kérésmodellek, hibakezelés, opcionális API-token és a HTTP-végpontok. |
| `tests/` | pytest-tesztek a teljes API-ra; minden teszt az adatbázis ideiglenes másolatán fut. |
| `requirements.txt` | A futtatáshoz szükséges csomagok: FastAPI, Uvicorn, bcrypt. |
| `requirements-dev.txt` | A tesztekhez szükséges további csomagok: pytest, httpx. |
| `pytest.ini` | A pytest beállításai. |
| `render.yaml` | Render webszolgáltatás-konfiguráció; telepítéskor függőségeket telepít, majd Uvicornnal indítja az API-t. |
| `futarszolgalat.db` | A csapat végleges, javított adatbázisa (`futarszolgalat_javitott.db`), adatokkal, nézetekkel, indexekkel és triggerekkel. |
| `ATTEKINTES.md` | Ez a dokumentum. |

## Az adatbázis

A `futarszolgalat.db` a DB-s csapat végleges exportjából (`futarszolgalat.db.sql`,
2026-10-15) készült a `futarszolgalat_javitas.sql` javító szkripttel. Ugyanez az
adatbázis van a Laravel-repóban is (`futarszolgalat/database/export/`), így a két
alkalmazás ugyanarra a sémára épül. A javítások röviden:

- a jelszavak bcrypt hashként tárolódnak (`$2y$` előtaggal, ezt a PHP/Laravel is
  ellenőrizni tudja);
- nincs drónos kiszállítás: a `futar.jarmu` csak `auto`, `bicikli` vagy `motor`
  lehet, az `ember` oszlop megszűnt;
- az új és lemondott rendeléseknek nincs futárja, egy futárnak legfeljebb egy
  aktív rendelése van, a futár állapota követi a rendeléseit;
- az időpontok (`letrehozva`, `kiszallitva_ido`, `frissitve`) ki vannak töltve, a
  futárpozíciók koordinátái fokban vannak (pl. 47.4979).

Fő táblák és kapcsolatok:

- `felhasznalo`: név, cím, telefonszám, egyedi e-mail, jelszóhash, `isAdmin`,
  `aktiv`;
- `futar`: név, egyedi telefonszám, jármű, állapot (`elerheto`, `uton`, `szunet`),
  hatósugár, `aktiv`;
- `futar_pozicio`: futáronként egy sor (`futarID` egyedi) a legutolsó pozícióval
  és a frissítés idejével;
- `fogas`: a fogások törzsadata (`kod`, `tipus`); a termék `(fogas, tipus)` párjának
  itt léteznie kell;
- `termek`: étel vagy ital, ár, elkészítési idő, prioritás, `aktiv`,
  `allergen_ellenorizve`;
- `allergen` és `termek_allergen`: allergének és a termékekhez kötésük;
- `rendeles`: megrendelő, futár (új rendelésnél még nincs), cím, km, fizetés,
  számlakérés, szállítási díj, státusz, értékelés, jatt, létrehozás és kiszállítás
  ideje;
- `rendeles_tetel`: rendelés–termék–darabszám, a rendeléskori egységárral;
- `szamlazasi_adat`: a számlát kérő rendelések számlázási neve, címe, adószáma.

Az adatbázis maga is sokat ellenőriz: CHECK-ek (pl. jatt csak kiszállított, kártyás
rendelésen; futár kell minden `kosar`/`új`/`lemondva` utáni státuszban), triggerek
(a futár aktív-e, belefér-e a hatósugárba; az egységár és a kiszállítás ideje
automatikusan kitöltődik) és `ON DELETE RESTRICT` kulcsok. Emiatt felhasználót,
futárt nem törlünk, hanem inaktiválunk (`aktiv = 0`), és rendelésben már szerepelt
terméket sem lehet törölni, csak inaktiválni.

## Működési rétegek

### Modellek – `modellek.py`

Az `Allergen`, `Fogas`, `Felhasznalo`, `Futar`, `FutarPozicio`, `Termek`,
`RendelesTetel`, `SzamlazasiAdat` és `Rendeles` adat-osztályok az alkalmazás
fogalmait képviselik. A konstruktorok ugyanazokat a szabályokat ellenőrzik, mint
az adatbázis CHECK-jei, plusz az üzleti szabályokat (pl. telefonszám `+36` vagy
`06` kezdettel, ételnél kötelező elkészítési idő, adószám formátuma).

A `Felhasznalo.regisztral()` legalább 8 karakteres jelszót fogad el, és csak a
bcrypt hasht tárolja; a bejelentkezés `bcrypt.checkpw`-vel ellenőriz. A rendelés
a tételek rendeléskori egységárából számolja a termékösszeget, a végösszegbe a
szállítási díj és a jatt is beleszámít (mint a `v_rendeles_osszeg` nézetben).

### Adatbázis – `adatbazis.py`

Az adatbázis alapból az `adatbazis.py` melletti `futarszolgalat.db`; a
`FUTARSZOLGALAT_DB` környezeti változóval más fájl adható meg (a tesztek így
dolgoznak másolaton). A `kapcsolat()` csak már létező adatbázist nyit meg,
bekapcsolja az idegen kulcsok ellenőrzését, sikeres művelet után commitol, hiba
esetén rollbackel. Sémát nem hoz létre és nem módosít.

A több lépésből álló műveletek egy tranzakcióban futnak, az állapotváltások
feltételes `UPDATE`-tel (`WHERE ... AND statusz = ...`). Így például ha két futár
egyszerre próbálja felvenni ugyanazt a rendelést, csak az egyiknek sikerül, a
másik `409`-et kap.

A hibákat három kivételtípus jelzi: `NemTalalhato` (404), `JogosultsagHiba` (403,
pl. nem a saját rendelés) és `UzletiHiba` (409, pl. rossz státuszban lévő
rendelés); a modellek érvénytelen adatra `ValidacioHiba`-t (400) dobnak.

### Rendelési folyamat

```
új --(futár felveszi)--> elfogadva --(konyha)--> készül --(futár átveszi)--> úton --(futár átadja)--> kiszállítva
 \--(megrendelő lemondja)--> lemondva          (elfogadva -> úton is lehet, ha a konyha lépése kimarad)
```

- Rendelést csak aktív felhasználó adhat le, aktív termékekből, legalább egy
  tétellel. Az új rendelés `új` státuszú, futár nélkül; a cím és a számlázási adat
  alapból a felhasználóé.
- A tételeket csak `új` státuszban lehet módosítani; ugyanaz a termék újra
  hozzáadva a darabszámot növeli; az utolsó tétel nem törölhető (helyette le kell
  mondani a rendelést). Lemondani is csak `új` rendelést lehet.
- Futár csak aktív, `elerheto`, aktív rendelés nélküli állapotban vehet fel
  rendelést, és csak a hatósugarán belül. Felvételkor `uton` lesz, kiszállítás után
  újra `elerheto`. Kézzel csak `elerheto` és `szunet` között vált, aktív rendelés
  nélkül.
- Értékelni (1–5) és jattot adni csak kiszállított rendelésnél lehet, egyszer;
  jattot csak kártyás fizetésnél. Ezeket csak a megrendelő teheti meg.
- Pozíciót csak úton lévő futár rögzíthet; a futár egyetlen pozíció-sora
  felülíródik.

### HTTP API – `api.py`

A felhasználói és futár-műveleteknél a kérés törzsében a műveletet végző
felhasználó (`felhasznalo_id`) vagy futár (`futar_id`) azonosítója szerepel; a
bejelentkeztetést és a munkamenetet a hívó (a Laravel backend) kezeli.

| Metódus | Útvonal | Művelet |
| --- | --- | --- |
| `POST` | `/bejelentkezes` | E-mail és jelszó ellenőrzése (csak aktív felhasználó); a publikus felhasználói adatokat adja vissza. |
| `POST` | `/felhasznalo` | Felhasználó regisztrálása; a létrehozott felhasználót adja vissza. |
| `GET` | `/felhasznalo` | Felhasználók keresése és lapozása (`aktiv`, `admin` szűrővel is). |
| `GET` | `/felhasznalo/{felhasznalo_id}` | Felhasználó lekérdezése azonosító alapján. |
| `GET` | `/felhasznalo/email/{email}` | Felhasználó lekérdezése e-mail-cím alapján. |
| `PUT` | `/felhasznalo/{felhasznalo_id}` | Adatok módosítása; `jelszo` nélkül a jelszó nem változik; `aktiv` is állítható. |
| `DELETE` | `/felhasznalo/{felhasznalo_id}` | Inaktiválás (nem törlés); a rendelések megmaradnak. |
| `GET` | `/felhasznalo/{felhasznalo_id}/rendelesek` | A felhasználó rendelései, legújabb elöl. |
| `POST` | `/futar/bejelentkezes` | Futár azonosítása névvel és telefonszámmal (csak aktív futár). |
| `POST` | `/futar` | Futár felvétele. |
| `GET` | `/futar` | Futárok keresése és lapozása. |
| `GET` | `/futar/elerheto` | Aktív, elérhető, aktív rendelés nélküli futárok. |
| `GET` | `/futar/allapotok` | A három futárállapot és megnevezése. |
| `GET` | `/futar/szallitasra-alkalmas?km=5` | Elérhető futárok, akiknek a hatósugara legalább a megadott távolság. |
| `POST` | `/futar/pozicio` | Az úton lévő futár aktuális pozíciójának rögzítése (felülírja az előzőt). |
| `GET` | `/futar/{futar_id}` | Futár lekérdezése. |
| `PUT` | `/futar/{futar_id}` | Futár adatainak módosítása (`aktiv` is). |
| `DELETE` | `/futar/{futar_id}` | Inaktiválás (nem törlés); aktív rendeléssel `409`. |
| `PATCH` | `/futar/{futar_id}/allapot` | Kézi állapotváltás: `elerheto` ↔ `szunet`. |
| `GET` | `/futar/{futar_id}/pozicio` | A futár aktuális pozíciója (vagy `null`). |
| `GET` | `/futar/{futar_id}/rendelesek` | A futár rendelései, legújabb elöl. |
| `GET` | `/futar/{futar_id}/felveheto-rendelesek` | Felvehető új rendelések a hatósugarán belül, a prioritásosak elöl. |
| `GET` | `/fogas` | Fogások és típusuk. |
| `GET`, `POST` | `/allergen` | Allergének listázása, felvétele (név egyedi, kis-/nagybetűtől függetlenül). |
| `PUT`, `DELETE` | `/allergen/{kod}` | Allergén átnevezése, törlése (használatban lévőnél `409`). |
| `POST` | `/termek` | Termék felvétele allergénkódokkal. |
| `GET` | `/termek` | Termékek keresése/szűrése és lapozása (`aktiv` szűrővel is), allergénekkel. |
| `GET` | `/termek/{termek_id}` | Termék lekérdezése. |
| `PUT` | `/termek/{termek_id}` | Termék módosítása, az allergénlistát is lecseréli; inaktiválás: `aktiv: false`. |
| `DELETE` | `/termek/{termek_id}` | Törlés, ha még nem rendelték; különben `409`. |
| `POST` | `/rendeles` | Rendelés leadása (`új`, futár nélkül), tételekkel és opcionális számlázási adattal. |
| `GET` | `/rendeles` | Rendelések keresése/szűrése és lapozása (`letrehozva_tol`, `letrehozva_ig` is). |
| `GET` | `/rendeles/statuszok` | A lehetséges rendelési státuszok. |
| `GET` | `/rendeles/{rendeles_id}` | Rendelés a tételeivel, egységárakkal, számlázási adattal, összegekkel. |
| `GET` | `/rendeles/{rendeles_id}/allergenek` | A rendelés termékeiben előforduló allergének egyedi listája. |
| `POST` | `/rendeles/{rendeles_id}/tetelek` | Tétel hozzáadása (megrendelő, `új` státuszban). |
| `PATCH`, `DELETE` | `/rendeles/{rendeles_id}/tetelek/{termek_id}` | Darabszám módosítása, tétel törlése (`DELETE`-nél `?felhasznalo_id=`). |
| `POST` | `/rendeles/{rendeles_id}/lemondas` | Lemondás (megrendelő, `új` státuszban). |
| `POST` | `/rendeles/{rendeles_id}/felvetel` | A futár felveszi: `új` → `elfogadva`. |
| `POST` | `/rendeles/{rendeles_id}/keszul` | A konyha készíti: `elfogadva` → `készül`. |
| `POST` | `/rendeles/{rendeles_id}/atvetel` | A futár átveszi: `elfogadva`/`készül` → `úton`. |
| `POST` | `/rendeles/{rendeles_id}/kiszallitas` | A futár átadja: `úton` → `kiszállítva`. |
| `POST` | `/rendeles/{rendeles_id}/ertekeles` | Értékelés 1–5 (megrendelő, kiszállítás után, egyszer). |
| `POST` | `/rendeles/{rendeles_id}/jatt` | Jatt (megrendelő, kiszállítás után, kártyás fizetésnél, egyszer). |

Rendelési státuszt általánosan beállító végpont nincs: a státusz csak a fenti
folyamatlépésekkel változhat. A válaszkódok: `400` érvénytelen adat, `401` hibás
bejelentkezés vagy API-token, `403` nem a saját rendelés, `404` nem található,
`409` üzleti szabályba vagy adatbázis-korlátozásba ütközik, `422` hiányzó vagy rossz
típusú mező a kérésben. A FastAPI interaktív dokumentációja a `/docs` útvonalon
érhető el.

#### API-token

Ha az `API_TOKEN` környezeti változó be van állítva, minden író kérés (`POST`,
`PUT`, `PATCH`, `DELETE`) csak `Authorization: Bearer <token>` fejléccel megy át,
különben `401`. Az olvasó végpontok és a dokumentáció nyilvánosak maradnak.
Renderen a tokent a szolgáltatás környezeti változói között kell megadni, a
Laravelben ugyanezt a tokent kell beállítani (`PYTHON_API_TOKEN`). Ha nincs
beállítva, az API védelem nélkül fut, ahogy eddig.

#### Elérés Renderből és PHP-ből

Az API Renderen beállított alapcímét a Render Dashboard szolgáltatásoldalán
lehet megnézni. Ne rögzítsd a szolgáltatás konkrét URL-jét a repóban; a PHP
alkalmazás konfigurációjából add meg környezeti változóként.

- Interaktív API-dokumentáció: `<API-alapcím>/docs`
- Példa elérhető futárok lekérésére: `GET <API-alapcím>/futar/elerheto`
- Példa rendelés felvételére:
  `POST <API-alapcím>/rendeles/123/felvetel` `{"futar_id": 5}`

A PHP backend teljes URL-re küldött HTTP-kéréssel, JSON-adatcserével hívja az
API-t; nem kell közvetlenül csatlakoznia a Python alkalmazáshoz vagy az SQLite
fájlhoz. Az API gyökérútvonala (`/`) nem szolgál ki kezdőoldalt, ott a `404 Not
Found` válasz normális.

## Indítás, tesztek és telepítés

Python 3.10 vagy újabb szükséges. Windows PowerShellben virtuális környezetből
például így indítható:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn api:app --reload
```

macOS-en és Linuxon ugyanez: `python3 -m venv .venv`, `source .venv/bin/activate`.
Ezután az API a `http://127.0.0.1:8000` címen érhető el, a dokumentáció a
`http://127.0.0.1:8000/docs` címen.

Tesztek futtatása (az adatbázis másolatán, a repó fájlja nem változik):

```powershell
python -m pytest
```

A Render konfiguráció ugyanezt az `api:app` ASGI-alkalmazást indítja, a
szolgáltatás által megadott porton.

## Fontos határok és megjegyzések

- A Render ingyenes csomagjában a fájlrendszer nem tartós: újraindításkor vagy új
  telepítéskor az API-n keresztül beírt adatok elvesznek, és a repóban lévő
  `futarszolgalat.db` áll vissza. Tartós működéshez tartós tárhely kell (a
  `FUTARSZOLGALAT_DB` változóval oda lehet irányítani az adatbázist).
- Az API maga nem kezel munkamenetet és szerepköröket: hogy ki adminisztrátor, és
  hogy a kérésben szereplő `felhasznalo_id`/`futar_id` tényleg a bejelentkezett
  felhasználóé-e, azt a hívó (Laravel) ellenőrzi. Ezért kell élesben az
  `API_TOKEN`, hogy csak a Laravel tudjon írni.
- A `kosar` státuszt az adatbázis engedi, de az API nem hoz létre kosár-rendelést:
  a kosarat a hívó kezeli, és egyben adja le a rendelést.
- A `szallitasi_dij` mindig 0 (az adatbázis alapértéke): a díjszámítás szabálya még
  nincs meghatározva.
- A futárpozíciókat egy másik csapat MongoDB-ben is kezeli; hogy az SQLite
  `futar_pozicio` tábla hosszú távon megmarad-e, még nincs eldöntve.
