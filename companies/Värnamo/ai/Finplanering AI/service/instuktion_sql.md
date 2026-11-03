# AI Omplanering — Instruktion SQL-tjänst (v4)

> **Version:** 4.0 | **Datum:** 2026-09-09
> **Gäller:** körning som tjänst mot SQL Server, utan Excel och utan UI.
>
> Detta dokument beskriver **enbart skillnaderna** mot `..\instuktion.md`.
> Affärsreglerna — frysning, EDD, artikel-klustring med räckviddsfönster och
> skadeprövning, kalenderkapacitet, alternativruttning, lead-time-propagation,
> prioritetstilldelning och statusdefinition — är **identiska**. Samma
> beräkningsmotor (`omplanering_core.compute_plan`) kör i båda vägarna, vilket
> är verifierat rad för rad.

---

## 1. Arkitektur

```
SQL Server (BIzparc_Direct_VMO_AI)
        │
        │  sql_source.load_source_sql()      ← fyra källtabeller
        ▼
   SourceData  ──►  omplanering_core.compute_plan()  ──►  PlanOutcome
                        (samma motor som appen)              │
                                                             │
        ┌────────────────────────────────────────────────────┘
        ▼  sql_sink.write_outcome()          ← en transaktion
SQL Server: tblAIAnglysisRun + tblAIAnglysisGetAoColorCodeList
```

`compute_plan` är källagnostisk. Excel-vägen (`run_replanning`) och
SQL-vägen använder exakt samma funktion; det enda som skiljer är
inläsningen och utskrivningen.

---

## 2. Källtabeller

| Tabell | Motsvarar Excel-flik | Anmärkning |
|---|---|---|
| `dbo.tblSTGetAoColorCodeList` | `tblSTGetAoColorCodeLis` | ⚠️ **`t` på slutet.** Excel-fliken är avkortad, SQL-tabellen inte. |
| `dbo.tblSTAllOperationsForAoNr` | samma | Auktoritativ för operationstider och `ProdGr` |
| `dbo.tblSTGetDateCalenderWorkingTime` | samma | |
| `dbo.tblSTProductionGroupPrioOnItem` | samma | |

### 2.1 Datatypsskillnader som måste hanteras

Detta är den enda tekniskt känsliga delen av SQL-vägen. Excel och SQL
levererar samma information i olika former:

| Fält | Excel | SQL Server | Hantering |
|---|---|---|---|
| Alla datumkolumner i baslinjen | float (Excel-serienummer) | `datetime` | Ingen konvertering behövs. `excel_serial_to_datetime()` klarar båda, men SQL-loadern castar explicit med `pd.to_datetime`. |
| `arbtimperdag`, `arbtimperdag_firstdaymode` | float | `numeric(7,3)` → **`decimal.Decimal`** | **Måste castas till float.** Decimal blandat med float kastar `TypeError` i kalenderaritmetiken. |
| `komtid`, `gicktid` | str `'06:00:00.0000000'` | `time(7)` → `datetime.time` | Används bara som reserv när `Date_komtid`/`Date_gicktid` saknas. |
| `dDate` | str `'2027-01-07'` | `date` | `pd.to_datetime` |
| `Prio1`–`Prio8` | float | `nvarchar(5)` | `normalize_prodgr()` klarar båda |
| `ProdGr` | int/float | `nvarchar(20)` resp. `nvarchar(5)` | `normalize_prodgr()` → strippad heltalssträng |

### 2.2 Batchhantering

`tblSTGetAoColorCodeList` har `LogCreatDateTime NOT NULL`. Två fall:

- **Tabellen laddas om vid varje uttag** (ett enda `LogCreatDateTime`) —
  läs allt. Detta är förvalet, `ONLY_LATEST_BATCH = false`.
- **Tabellen appendar** (flera `LogCreatDateTime`) — då måste bara senaste
  batchen läsas, annars blandas uttag. Sätt `ONLY_LATEST_BATCH = true`.

Tjänsten **räknar antalet distinkta `LogCreatDateTime` vid varje körning** och
skriver en datavalideringsanmärkning om de är fler än ett medan förvalet
gäller. Det gissas alltså aldrig — avvikelsen rapporteras.

### 2.3 Rimlighetsspärr

Om `tblSTGetAoColorCodeList` innehåller färre rader än `MIN_BASELINE_ROWS`
avbryts körningen **utan att något skrivs**. Ett halvfärdigt eller tömt uttag
får aldrig skriva över ett giltigt resultat.

---

## 3. Resultatlagring

### 3.1 Två tabeller, append med `RunId`

Resultatet skrivs inte över. Varje körning får ett eget `RunId`:

| Tabell | Innehåll |
|---|---|
| `dbo.tblAIAnglysisRun` | En rad per körning: policy, statusgräns, nyckeltal, varningar, status (`Klar`/`Fel`), feltext och körtid. Ersätter Excel-fliken `AI_Sammanfattning`. |
| `dbo.tblAIAnglysisGetAoColorCodeList` | En rad per tillverkningsorder och körning. |

Motivet: körhistorik gör två körningar jämförbara, en misslyckad körning
lämnar föregående resultat orört, och `tblAIAnglysisRun` blir en driftlogg som
går att larma på.

Vyn `dbo.vwAIAnglysisSenaste` ger alltid senaste **lyckade** körningen — använd
den i Power BI och rapporter i stället för att filtrera på `RunId`.

Proceduren `dbo.uspAIAnglysisPurge @KeepRuns` städar. Tjänsten anropar den
efter varje lyckad körning med `RETENTION_RUNS` (förval 30).

### 3.2 Kolumner utöver Excel-mallen

Excel-mallens 21 kolumner finns med i samma ordning. Utöver dem lagras
härledda värden, så att tabellen går att fråga på utan att tolka fritexten i
`AI_Kommentar`:

| Kolumn | Innebörd |
|---|---|
| `Orginal_MarginalDygn`, `AI_MarginalDygn` | Leveransmarginal i hela dygn: `OrdBerLevDat − klartid` |
| `Orginal_ForseningDygn`, `AI_ForseningDygn` | Försening i **arbetsdagar** enligt skiftkalendern — se 3.3. Differensen visar om en redan försenad order blivit **mer** försenad |
| `Orginal_ColorName_AIRegel` | Utgångsstatus bedömd med **samma** regel som `AI_ColorName` — jämförbar. `Orginal_ColorName` är Jeeves råa värde och rörs inte |
| `AI_Fryst`, `AI_FrysOrsak` | Om och varför raden frystes (2.1) |
| `AI_Omrutad`, `AI_OmrutadFran` | Maskinbyte via Prio1–Prio8 |
| `AI_StalltidSparadH`, `AI_KlustradMotAoNr` | Ställtidsbesparing och mot vilken order |
| `AI_Framdragen`, `AI_FramdragenKostnadDygn` | Om ordern drogs fram förbi EDD, och vad skadeprövningen bedömde att det kostade (2.3) |

### 3.3 Försening i arbetsdagar (NYTT)

Tjänsten räknar förseningen i **arbetsdagar enligt skiftkalendern**, inte i
kalenderdygn. Helger och röda dagar räknas inte som försening.

```
ForseningDygn = antal arbetsdagar d där  OrdBerLevDat < d ≤ klartid
```

Levereras en order på måndag i stället för fredag blir förseningen alltså
**1**, inte 3.

**Arbetsdagarna är desamma för alla order, oavsett vilket kalendernr AoNr
körs på.** Tjänsten bygger en gemensam *företagskalender* ur
`tblSTGetDateCalenderWorkingTime`:

> En dag är arbetsdag om den är **måndag–fredag** och är arbetsdag
> (`arbtimperdag > 0`) i **en klar majoritet** av de kalendrar som täcker dagen.

Helger räknas aldrig. Röda dagar och julstängning faller bort eftersom de
saknas i de flesta kalendrar, medan en enskild kalender som kör en helgdag inte
räcker för att göra den till arbetsdag. I nuvarande underlag ger det:

| Dag | Kalendrar som kör | Företagskalender |
|---|---|---|
| 24/12–1/1, 6/1 | ingen | ej arbetsdag |
| 23/12, långfredag, Kristi himmelsfärd + klämdag | kal 6 (1 av 4) | ej arbetsdag |
| Annandag påsk | kal 2, 6 (2 av 4 – ingen majoritet) | ej arbetsdag |
| Lördag, söndag | kal 2, ibland 6 | ej arbetsdag (helg) |
| Övriga vardagar | alla | arbetsdag |

Resultatet är i dag identiskt med kal 7 och 90, men beror inte på att just
de kalendrarna finns eller ser ut som de gör.

| Regel | Innebörd |
|---|---|
| **Kalender** | `DELAY_CALENDAR` — förval **`"foretag"`** enligt ovan. Ett kalendernr (t.ex. `7`) ger en bestämd kalender för alla order. `"egen"` ger orderns egen Op10-kalender, men kal 2 och 6 har söndag som arbetsdag, så då räknas söndagar som försening (i nuvarande underlag 8 266 i stället för 6 915 dagar). |
| **Samma måttstock före och efter** | `Orginal_` och `AI_` räknas mot samma kalender, även om ordern omrutats till en maskin med annan kalender. |
| **Utanför kalendern** | Kalendern börjar vid uttagsdagen. För en förseningsperiod som börjar tidigare räknas dagarna efter kalenderns eget veckomönster (härlett ur datat: veckodagar som är arbetsdagar minst hälften av gångerna). Röda dagar bakåt i tiden kan inte kännas till. Antalet sådana order redovisas som en datavalideringsanmärkning. |
| **Påverkar inte** | Statusfärgen, `AI_MarginalDygn`, planeringen eller klustringens skadeprövning — de räknar fortfarande i kalenderdygn (instruktion 2.4). |

`LateDaysBefore`, `LateDaysAfter`, `LateDaysBeforeRed`, `LateDaysAfterRed`
och `WorstDays` i `tblAIAnglysisRun` räknas med samma funktion, så
`SUM(AI_ForseningDygn)` är alltid lika med `LateDaysAfter`. Enheten och
grunden loggas per körning i `DelayUnit` (`arbetsdagar/företag`,
`arbetsdagar/kal 7`, `arbetsdagar/egen` eller `dygn`); `DelayCalendarNr` är
satt bara när ett bestämt kalendernr används.

Skrivbordsappen räknar fortsatt i kalenderdygn (`DELAY_IN_WORKDAYS = False` i
motorn); tjänsten slår på arbetsdagar via `config.py`.

### 3.4 Transaktion

Körloggens rad och alla resultatrader skrivs i **en** transaktion. Antingen
finns hela körningen, eller ingen del av den. Vid fel görs `ROLLBACK` och en
rad med `Status = 'Fel'` och feltexten skrivs separat till `tblAIAnglysisRun`.

---

## 4. Samtidighet och drift

### 4.1 Applås

Före varje körning tas `sp_getapplock` med `@LockOwner = 'Session'`. Två
instanser kan därför aldrig skriva samtidigt. Den som inte får låset avslutar
med exitkod **2** utan att röra något. Låset är sessionsbundet och släpps även
om processen dör.

### 4.2 Exitkoder

| Kod | Betydelse |
|---|---|
| `0` | Klart |
| `1` | Fel — se loggen och `tblAIAnglysisRun.ErrorMessage` |
| `2` | En annan körning pågick; ingenting gjordes |

Task Scheduler kan larma på kod 1. Kod 2 är inte ett fel.

### 4.3 Tidszon

Frysningsregeln (2.1) jämför alltid mot **Europe/Stockholm**, oavsett
serverns lokala tidszon eller SQL Serverns `GETDATE()`. `NowStockholm`
loggas per körning i `tblAIAnglysisRun` så att utfallet går att rekonstruera.

---

## 5. Konfiguration

Allt ligger i `config.py` och kan överstyras av en `config.json` bredvid, utan
kodändring. Okända nycklar i JSON-filen ger fel vid start i stället för att
ignoreras tyst.

| Nyckel | Förval | Betydelse |
|---|---|---|
| `SERVER_NAME`, `DATABASE` | `AHO-APP12`, `BIzparc_Direct_VMO_AI` | Trusted Connection, inga lösenord i kod |
| `ODBC_DRIVER` | `SQL Server` | Byt till `ODBC Driver 17 for SQL Server` om den finns — snabbare, bättre `fast_executemany` |
| `CLUSTER_WINDOW_DAYS` | `30` | N2: räckviddsfönster |
| `TARDINESS_BUDGET_PER_SETUP_HOUR` | `0` | N3: skadebudget |
| `PROTECT_MARGIN_DAYS` | `0` | N3: vad som räknas som skada |
| `GREEN_MARGIN_DAYS` | `1` | 2.4: statusgräns |
| `DELAY_IN_WORKDAYS` | `true` | Försening i arbetsdagar i stället för kalenderdygn (3.3) |
| `DELAY_CALENDAR` | `"foretag"` | Arbetsdagar lika för alla order, oavsett kalendernr. Alternativ: ett kalendernr, eller `"egen"` (3.3) |
| `SCHEDULE_TIMES` | `05:30, 11:30, 17:30` | Körtider i `--loop`-läge |
| `RETENTION_RUNS` | `30` | Antal körningar som sparas |
| `ONLY_LATEST_BATCH` | `false` | Se 2.2 |
| `MIN_BASELINE_ROWS` | `1` | Se 2.3 |
| `EXPORT_DIR` | `null` | Valfri Excel-/CSV-kopia per körning |

**Policyn loggas i varje körning** (`tblAIAnglysisRun`), så ett resultat går
alltid att härleda till de inställningar som gällde.

---

## 6. Driftsättning

1. Kör `sql\01_create_tables.sql` en gång mot `BIzparc_Direct_VMO_AI`.
2. Installera beroenden: `pip install -r service/requirements.txt`.
3. Kontrollera: `python run_service.py --check`.
4. Provkör utan att skriva: `python run_service.py --dry-run`.
5. Registrera schemat: `.\install_task.ps1 -RunAsUser "DOMÄN\konto"`.

Tjänstekontot behöver `SELECT` på de fyra källtabellerna, `INSERT`/`DELETE` på
de två resultattabellerna, `EXECUTE` på `uspAIAnglysisPurge`, samt *Log on as a
batch job* på servern.

---

## 7. Kända fällor (utöver `..\instuktion.md` avsnitt 7)

| Fälla | Hantering |
|---|---|
| `numeric` → `Decimal` blandat med float | Castas explicit i `sql_source._coerce()` innan något räknas |
| Tabellnamnet `...CodeLis` vs `...CodeList` | SQL-tabellen har `t` på slutet; Excel-fliken inte |
| Flera uttag blandade i källtabellen | Antalet distinkta `LogCreatDateTime` kontrolleras och rapporteras (2.2) |
| Tömt eller halvfärdigt uttag | `MIN_BASELINE_ROWS` avbryter innan något skrivs (2.3) |
| Två samtidiga körningar | `sp_getapplock`; den andra avslutar med kod 2 (4.1) |
| Delvis skrivet resultat vid krasch | En transaktion runt hela skrivningen (3.4) |
| Resultattabellen växer | `uspAIAnglysisPurge` efter varje lyckad körning (3.1) |
| Serverns tidszon ≠ Europe/Stockholm | Frysningen använder alltid Europe/Stockholm (4.3) |
