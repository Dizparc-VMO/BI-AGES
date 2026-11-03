# AI Omplanering V5

V5 finns parallellt med V4. De befintliga V4-filerna ändras inte.

## Skrivbordsapp

Installera beroenden från projektroten och starta V5:

```powershell
python -m pip install -r requirements.txt
python omplanering_app_v5.py
```

Appen läser samma arbetsboksformat som tidigare och skriver tidsstämplade Excel- och CSV-resultat till vald utdatakatalog med filnamn som innehåller `_v5_resultat_`.

## SQL-tjänst

Installera tjänstens beroenden och kör från projektroten:

```powershell
python -m pip install -r service/requirements.txt
python service/run_service_v5.py --dry-run
```

`--dry-run` läser och beräknar men skriver inte planresultat till SQL. För att skriva en körning används `--once`; kontrollera anslutning och behörigheter först med `--check`. V5 återanvänder SQL-anslutnings-, logg-, styrtabells- och konfigurationsmodulerna i `service/`. Den läser klusterfönstret från befintlig konfiguration; V4:s setup-skadebudget används inte av V5.

Innan V5-resultat skrivs till SQL, kör först `service/sql/01_create_tables.sql` om grundtabellerna saknas och därefter `service/sql/02_v5_objective_metrics.sql` för V5:s poäng- och takkolumner.

## Tester

Från projektroten:

```powershell
python -m unittest test_omplanering_v5 -v
```

Testerna täcker poängtrappans gränser, lika ordervikt oavsett operationstid, 4-timmarsgränsen, lokal cap-reparation, återställning vid ofullständig plan och kalenderns täckningsgräns.

V5-motorn är heuristisk och ger ingen garanti om globalt optimal plan. Om en order överskrider sitt tak låses just den ordern till ursprunglig tid och maskin, och återstående kö schemaläggs om. Om takbrott eller oplanerat arbete kvarstår efter lokal reparation avvisas kandidaten och hela originalplanen behålls. Det bevisar inte att en bättre cap-säker plan är omöjlig. Granska varningar och befintliga överlapp i originalplanen innan resultatet används operativt.