# AI Omplanering V7

V7 är en fristående kundviktad version. Den använder egna motor-, app-, test- och servicefiler. V5/V6 och den befintliga SQL-tjänsten ändras inte.

## Skrivbordsapp

Kör från projektroten:

```powershell
python omplanering_app_v7.py
```

Välj arbetsboken och utkatalogen. Kontrollera följande körningsfält innan du startar:

- Låshorisont: standard 4 timmar.
- Generell maxförsening: standard 10 kalenderdagar.
- Poängtrappa med redigerbara intervall: `Från`, `Till` och fast `Poäng`.
  Lägg till eller ta bort intervall i gränssnittet. Förseningsdagar avrundas
  uppåt till hela dagar, ändpunkter ingår och det sista `Till` lämnas tomt för
  ett obegränsat intervall.
- Klusterfönster: standard 30 dagar.

Decimalvärden i övriga V7-policyfält godtas med punkt eller komma. Intervallens
daggränser ska vara heltal. Poäng måste vara ändliga och icke-negativa; raderna
ska täcka dag 0 till obegränsat utan luckor eller överlapp. Inställningar sparas
separat i `.omplanering_ui_v7.json`.

## Kunddata

Lägg till fliken `CustomerConfig` med kolumnerna `OrderNumber`, `Customer`, `Vikt` och `MaxLate`. `OrderNumber` måste matcha baslinjens `OrderNr`.

Kundvikt påverkar kundviktad grönprioritet och förseningspoäng. Saknad/okänd kund använder vikt 1 och generell maxförsening. Ifyllt `MaxLate` ersätter det generella värdet. En AO med flera kundordrar får högsta kundvikt och lägsta kundtak.

**Kontrollera joinen före körning.** Bekräfta att `CustomerConfig.OrderNumber`
matchar baslinjens `OrderNr`. Om inga värden matchar används standardpolicyn
(vikt 1 och generell maxförsening), så kör inte en produktionsplan med
kundviktning innan nycklarna har verifierats.

## SQL-tjänst

SQL-varianten finns separat i `service/`:

```powershell
python service/run_service_v7.py --check
python service/run_service_v7.py --dry-run --force
```

Innan den används:

1. Kör `service/sql/03_v7_customer_config_and_metrics.sql` i `BIzparc_Direct_VMO_AI`.
2. Ladda och verifiera `dbo.CustomerConfig` med samma fyra kolumner och kontrollera `OrderNumber` mot `OrderNr`.
3. Ställ in anslutning och policy i `service/config_v7.py` eller `service/config_v7.json`.
4. Godkänn dry-run innan Task Scheduler registreras med `service/install_task_v7.ps1`.

CLI kan tillfälligt ändra policyn, exempelvis:

```powershell
python service/run_service_v7.py --dry-run --force --max-late 10 `
--score-band=-99:0:1 --score-band=1:2:2 --score-band=3:4:4 `
--score-band=5:7:9 --score-band=8:9:10 --score-band=10:*:20
```

`--score-band` kan upprepas; formatet är `FRÅN:TILL:POÄNG` och `*` anger
obegränsad övre gräns i det sista intervallet.

Kunddata laddas av den ordinarie datakällan; SQL-tjänsten skriver inte till `CustomerConfig`.

## Tester och begränsningar

Kör V7-tester:

```powershell
python -m unittest test_omplanering_v7 -v
```

V7 planerar Op10 med kalenderstyrd kapacitet, låsning, lokal reparation och
säkerhetsåterfall. Motorn är heuristisk och garanterar inte global optimalitet.
Kontrollera anmärkningar, material, verklig bemanning och maskinkapacitet före
frisläppning.

Se [instuktion_v7.md](instuktion_v7.md) för en fristående helhetsbeskrivning
med regler och instruktioner för båda körsätten, och
[dokumentation_v7.html](dokumentation_v7.html) för den visuella användarguiden
och exemplen. Den samlade lösningskontexten för V5–V7 finns i
[instuktion.md](instuktion.md).