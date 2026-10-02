CREATE TABLE IF NOT EXISTS allergen (
	kod INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	nev TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS felhasznalo (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	nev TEXT NOT NULL COLLATE NOCASE,
	cim TEXT NOT NULL,
	telszam TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS futar (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	nev TEXT NOT NULL COLLATE NOCASE,
	telszam TEXT NOT NULL,
	jarmu TEXT NOT NULL CHECK (jarmu IN ('auto', 'dron', 'bicikli', 'motor')),
	ember INTEGER NOT NULL DEFAULT 0 CHECK (jarmu != 'dron' OR ember = 0),
	allapot TEXT NOT NULL DEFAULT 'elerheto' CHECK (allapot IN ('elerheto', 'uton', 'szunet')),
	hatosugar_km INTEGER NOT NULL CHECK (hatosugar_km > 0)
);

CREATE TABLE IF NOT EXISTS futar_pozicio (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	futarID INTEGER NOT NULL,
	gps_x INTEGER NOT NULL,
	gps_y INTEGER NOT NULL,
	cim TEXT NOT NULL,
	FOREIGN KEY (futarID) REFERENCES futar(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rendeles (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	felhasznalo_id INTEGER NOT NULL,
	futar_id INTEGER NOT NULL,
	cim TEXT NOT NULL,
	prioritas INTEGER NOT NULL DEFAULT 0 CHECK (prioritas IN (0, 1)),
	fizetesi_mod TEXT NOT NULL CHECK (fizetesi_mod IN ('keszpenz', 'kartya')),
	jatt INTEGER CHECK (jatt > 0 AND fizetesi_mod = 'kartya'),
	szamla INTEGER NOT NULL CHECK (szamla IN (0, 1)),
	km INTEGER NOT NULL CHECK (km > 0),
	statusz TEXT NOT NULL DEFAULT 'új',
	ertekeles INTEGER NOT NULL CHECK (ertekeles IN (1, 2, 3, 4, 5)),
	FOREIGN KEY (felhasznalo_id) REFERENCES felhasznalo(id) ON DELETE CASCADE,
	FOREIGN KEY (futar_id) REFERENCES futar(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS termek (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	tipus TEXT NOT NULL DEFAULT 'etel' CHECK (tipus IN ('etel', 'ital')),
	nev TEXT NOT NULL COLLATE NOCASE,
	fogas TEXT NOT NULL,
	leiras TEXT,
	ar INTEGER NOT NULL CHECK (ar >= 0),
	elkeszitesi_ido INTEGER,
	prioritas INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rendeles_tetel (
	rendeles_id INTEGER NOT NULL,
	termek_id INTEGER NOT NULL,
	db INTEGER NOT NULL DEFAULT 1 CHECK (db >= 1),
	PRIMARY KEY (rendeles_id, termek_id),
	FOREIGN KEY (rendeles_id) REFERENCES rendeles(id) ON DELETE CASCADE,
	FOREIGN KEY (termek_id) REFERENCES termek(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS termek_allergen (
	termek_id INTEGER NOT NULL,
	allergen_kod INTEGER NOT NULL,
	PRIMARY KEY (termek_id, allergen_kod),
	FOREIGN KEY (allergen_kod) REFERENCES allergen(kod) ON DELETE CASCADE,
	FOREIGN KEY (termek_id) REFERENCES termek(id) ON DELETE CASCADE
);