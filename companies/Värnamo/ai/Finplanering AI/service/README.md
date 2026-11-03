# AI Omplanering — SQL-tjänst

Kör samma omplanering som skrivbordsappen, men mot SQL Server och utan UI.
Läser planeringsunderlaget ur `BIzparc_Direct_VMO_AI`, kör motorn i
`..\omplanering_core.py`, och skriver resultatet till
`tblAIAnglysisGetAoColorCodeList`.

Affärsreglerna är identiska med `..\instuktion.md`. Skillnaderna mot
Excel-vägen står i **[instuktion_sql.md](instuktion_sql.md)**.

---

## Så fungerar handskakningen

Tjänsten kör inte på klockan — den väntar på att din laddnings-SP säger till.

```
   SP laddar källtabellerna
            │
            ▼
   UPDATE dbo.sysRunScript
   SET Status = 0, SenastDTSPKor = GETDATE()      ← "data klar, kör!"
            │
            ▼
   Tjänsten pollar var 5:e minut, ser Status = 0, kör hela vägen
            │
            ▼
   Resultatet skrivet → Status = 1, SenastDTScriptKor = GETDATE()
                                                   ← "klar, väntar på ny data"
```

Misslyckas körningen lämnas `Status = 0` kvar, så nästa poll gör om försöket
på samma data. Varje försök loggas i `tblAIAnglysisRun`.

Hinner SP:n ladda en **ny** batch medan körningen pågår upptäcks det
(`SenastDTSPKor` har ändrats), grinden lämnas öppen och den nya batchen körs
vid nästa poll i stället för att tappas bort.

---

## Filer

| Fil | Roll |
|---|---|
| `run_service.py` | Startpunkt. Alla körlägen. |
| `run_gate.py` | Grinden mot `dbo.sysRunScript` |
| `sql_source.py` | Läser de fyra källtabellerna → `SourceData` |
| `sql_sink.py` | Skriver resultat + körlogg i en transaktion |
| `db.py` | Anslutning (Trusted Connection) och applås |
| `config.py` | Inställningar. Överstyrs av valfri `config.json` |
| `service_log.py` | Loggning till `logs\` och till husets `logToFile` om den finns |
| `sql\01_create_tables.sql` | Alla databasobjekt |
| `install_task.ps1` | Registrerar den schemalagda uppgiften |
| `instuktion_sql.md` | Specifikationen för SQL-varianten |

---

## Driftsättning

**1. Skapa databasobjekten** — kör `sql\01_create_tables.sql` en gång mot
`BIzparc_Direct_VMO_AI`. Skriptet är idempotent och skapar:

- `dbo.sysRunScript` (styrtabell, seedas i viloläge)
- `dbo.tblAIAnglysisRun` (körlogg)
- `dbo.tblAIAnglysisGetAoColorCodeList` (resultat)
- `dbo.vwAIAnglysisSenaste` (senaste lyckade körningen)
- `dbo.uspAIAnglysisPurge` (städning)

**2. Installera beroenden**

```bash
pip install -r requirements.txt
```

Den filen drar in projektets `requirements.txt` (pandas, openpyxl, tzdata) och lägger
till `pyodbc`. `tzdata` är obligatorisk på Windows – utan den hittar
`ZoneInfo("Europe/Stockholm")` ingen tidszonsdatabas och frysningsregeln
kraschar direkt.

**3. Kontrollera anslutning, tabeller och grind**

```bash
python run_service.py --check
```

**4. Provkör utan att skriva något**

```bash
python run_service.py --dry-run --force
```

`--force` förbigår grinden så att du kan testa utan att vänta på SP:n.

**5. Registrera schemat** — var 5:e minut, pollande:

```powershell
.\install_task.ps1 -RunAsUser "VMO\svc_aiomplanering"
```

**6. Låt SP:n släppa fram tjänsten.** Lägg detta sist i laddnings-SP:n:

```sql
UPDATE dbo.sysRunScript
SET    Status = 0,
       SenastDTSPKor = GETDATE();
```

---

## Körlägen

| Kommando | Vad det gör |
|---|---|
| `--once` | En körning om grinden är öppen. Detta använder Task Scheduler. |
| `--watch` | Långkörande process som pollar var 5:e minut. Alternativ till Task Scheduler. |
| `--dry-run` | Räknar och loggar nyckeltal, skriver ingenting. |
| `--check` | Kontrollerar anslutning, tabeller, kolumner, applås och grind. |
| `--loop` | Långkörande på fasta klockslag, utan grind. |

Tillägg: `--force` (kör oavsett grind), `--window N`, `--budget X`
(annan klustringspolicy för just den körningen).

### Exitkoder

| Kod | Betydelse |
|---|---|
| `0` | Klart |
| `1` | Fel — se loggen och `tblAIAnglysisRun.ErrorMessage` |
| `2` | En annan körning pågick; ingenting gjordes |
| `3` | Grinden stängd — inget att göra. **Inte ett fel.** |

Larma på kod `1`. Kod `2` och `3` är normala.

---

## Behörigheter

Tjänstekontot behöver:

- `SELECT` på de fyra källtabellerna
- `SELECT`, `UPDATE`, `INSERT` på `dbo.sysRunScript`
- `INSERT`, `DELETE` på de två resultattabellerna
- `EXECUTE` på `dbo.uspAIAnglysisPurge`
- *Log on as a batch job* på servern

---

## Läsa resultatet

Senaste lyckade körningen:

```sql
SELECT * FROM dbo.vwAIAnglysisSenaste ORDER BY AI_ProdGr, AI_OpkoPrioritet DESC;
```

Körhistorik med nyckeltal:

```sql
SELECT TOP 20 RunStart, Status, RowsTotal,
       RedBefore, RedAfter, LateDaysBefore, LateDaysAfter,
       WorseCount, WorstDays, SetupHoursSaved, PulledForward, Rerouted,
       DurationSeconds, WarningCount
FROM   dbo.tblAIAnglysisRun
ORDER  BY RunStart DESC;
```

Körplanen för en maskin:

```sql
SELECT AI_OpkoPrioritet, AoNr, ArtNr, AI_AoStartDatTid, AI_AoSlutDatTid,
       AI_ColorName, AI_MarginalDygn, AI_Kommentar
FROM   dbo.vwAIAnglysisSenaste
WHERE  AI_ProdGr = '10138'
ORDER  BY AI_OpkoPrioritet DESC;
```

Order som blev mer försenade än originalplanen. `ForseningDygn` räknas i
**arbetsdagar**, samma för alla order oavsett kalendernr: måndag–fredag som är
arbetsdag i en majoritet av kalendrarna — helger och röda dagar ingår inte. `MarginalDygn` är kalenderdygn. Se
[instuktion_sql.md](instuktion_sql.md) avsnitt 3.3.

```sql
SELECT AoNr, ArtNr, AI_ProdGr, Orginal_ForseningDygn, AI_ForseningDygn,
       AI_ForseningDygn - Orginal_ForseningDygn AS ForsamringDygn, AI_Kommentar
FROM   dbo.vwAIAnglysisSenaste
WHERE  AI_ForseningDygn > Orginal_ForseningDygn
ORDER  BY ForsamringDygn DESC;
```

---

## Felsökning

| Symptom | Orsak |
|---|---|
| Tjänsten kör aldrig | `Status` i `sysRunScript` är inte 0. Kontrollera att SP:n avslutar med `UPDATE ... SET Status = 0`. Kör `--check` för att se grindens läge. |
| Kör om och om igen | SP:n sätter Status = 0 vid varje anrop utan att data ändrats, eller så misslyckas körningen (Status lämnas då kvar på 0 med flit). Se `tblAIAnglysisRun.ErrorMessage`. |
| `pyodbc saknas` | `pip install pyodbc` |
| `TypeError` kring Decimal | Källtabellens `numeric`-kolumner castas i `sql_source._coerce()`. Har en ny numerisk kolumn tillkommit måste den läggas till i `NUMERIC_COLS`. |
| Varning om flera `LogCreatDateTime` | Källtabellen appendar. Sätt `"ONLY_LATEST_BATCH": true` i `config.json`. |
| Körningen avbryts direkt med kod 2 | Applåset är taget — en annan körning pågår. Normalt. |
| Resultattabellen växer | `RETENTION_RUNS` styr hur många körningar som sparas (förval 30). |
