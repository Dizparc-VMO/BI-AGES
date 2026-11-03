# AI Omplanering V7 – SQL-tjänst

V7 SQL-tjänst kör den fristående V7-motorn mot SQL Server. Befintliga `run_service.py`, V5/V6-filer och SQL-tjänst lämnas oförändrade.

## Databasschema

Kör först från SQL Server Management Studio:

```text
service/sql/03_v7_customer_config_and_metrics.sql
```

Skriptet skapar/validerar `dbo.CustomerConfig` och lägger till V7-policy- och kundspårningsfält i `dbo.tblAIAnglysisRun` och `dbo.tblAIAnglysisGetAoColorCodeList`. Det fyller inte kundrader.

`dbo.CustomerConfig` ska innehålla:

| Kolumn | Typ/rekommendation | Betydelse |
|---|---|---|
| `OrderNumber` | nvarchar(100) | Matchar baslinjens `OrderNr`. |
| `Customer` | nvarchar(100) | Kundnummer eller namn. |
| `Vikt` | decimal, strikt större än 0 | Kundprioritet. |
| `MaxLate` | decimal, NULL eller minst 0 | Kundens maxförsening i kalenderdagar. |

Global maxförsening och poängtrappa kan ställas i `config_v7.py` eller via en
separat `config_v7.json`. Poängtrappan består av raderna
`[frånDag, tillDag, poäng]`; `null` som sista övre gräns betyder obegränsat.
Förvalet är max 10 kalenderdagar och intervallen
`[-99,0]=1`, `[1,2]=2`, `[3,4]=4`, `[5,7]=9`, `[8,9]=10`, `[10,∞]=20`.
Gränserna är heltalsdagar med inkluderade ändpunkter. Faktisk försening avrundas
uppåt till hela dagar innan poängintervallet väljs.

## Säker start

1. Verifiera att `CustomerConfig.OrderNumber` faktiskt matchar `dbo.tblSTGetAoColorCodeList.OrderNr`. V7 använder inte `AoNr` som reservnyckel.
2. Kontrollera anslutning, CustomerConfig och resultatschema:

```powershell
python service/run_service_v7.py --check
```

3. Kör en beräkning utan SQL-skrivning:

```powershell
python service/run_service_v7.py --dry-run --force
```

4. Granska varningar, matchningsgrad, viktad grönprioritet, förseningspoäng och maxgränser.
5. Registrera en separat V7-schemalagd uppgift först när dry-run är godkänd:

```powershell
.\service\install_task_v7.ps1 -RunAsUser "VMO\svc_aiomplanering"
```

## Parametrar

`config_v7.json` kan innehålla valfria V7-överskrivningar, till exempel:

```json
{
  "DEFAULT_MAX_TARDINESS_DAYS": 10,
  "TARDINESS_SCORE_BANDS": [
    [-99, 0, 1], [1, 2, 2], [3, 4, 4],
    [5, 7, 9], [8, 9, 10], [10, null, 20]
  ],
  "CLUSTER_WINDOW_DAYS": 30
}
```

Per körning stöds bland annat:

```powershell
python service/run_service_v7.py --dry-run --force `
  --max-late 10 `
  --score-band=-99:0:1 --score-band=1:2:2 --score-band=3:4:4 `
  --score-band=5:7:9 --score-band=8:9:10 --score-band=10:*:20
```

`--score-band` kan upprepas. Varje värde har formatet
`FRÅN:TILL:POÄNG`; `*` betyder att sista intervallet saknar övre gräns.
Valideringen stoppar luckor, överlapp, brutna heltalsgränser och ogiltiga
poängvärden innan körningen.

## Kundregler

`MaxLate` i CustomerConfig ersätter globalt max för den OrderNumber-raden. Blank maxvärde använder globalgränsen. Okänd eller omatchad order använder vikt 1 och globalgränsen. Om flera kundordrar kopplas till samma AO används högsta vikt och striktaste (lägsta) maxvärde. En originalorder som redan överskrider taket får inte försämras ytterligare.

SQL-resultat sparas transaktionellt med RunId och innehåller kundnummer,
ordernummer, tillämpad vikt, maxvärde och vald intervallpoäng. Körloggen sparar
globalgräns, hela poängtrappan i `ScoreBandsJson`, viktad grönprioritet och
order över maxgräns. Kör den idempotenta V7-migrationen igen för att lägga till
`ScoreBandsJson` i befintliga installationer. Kundkonfigurationen är endast
indata; tjänsten skriver inte till den tabellen.