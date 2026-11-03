# AI Omplanering — lösningskontext, regler och krav för version 1

**Dokumenttyp:** Full lösningsspecifikation och kontext för Varnamo Finplanering AI. Detta är den auktoritativa dokumentationen för den aktuella versionen 1.
**Syfte:** Detta dokument beskriver bakgrund, affärslogik, dataflöden, systemgränser, säkerhet, SQL- och Excel-flöde samt krav på ändringar i lösningen. Det är inte en användarguide för slutlig appanvändning.

## 1. Syfte och lösningskontext

Lösningen beräknar ett genomförbart omplaneringsförslag för Operation 10 (Op10)
i Jeeves ERP:s tillverkningsorder (AO). Målet är att förbättra leveransutfallet,
minska förseningar och få en mer stabil, genomförbar plan utan att dölja
försämringar, bryta mot fysiska produktionsvillkor eller ändra operationer som
redan är låsta eller redan påbörjade.

Programmet används för att:

- utvärdera en AO-plan för Op10,
- flytta operationer inom tid, kalender och kapacitet,
- prioritera kund- och affärsnycklar i en transparent modell,
- skapa lokala Excel- och CSV-output,
- läsa in data från Excel eller SQL Server,
- uppdatera SQL-källinformation via en godkänd procedur,
- skriva resultat tillbaka till SQL i en separat, uttryckligt bekräftad transaktion.

Detta dokument gäller den aktuella version 1 som täcker den samlade lösningens
regelverk, datasmarta, UI-flöde och SQL-läge. Det är den enda dokumenterade
auktoriteten för hur lösningen ska förstås och utvecklas. Det ska inte delas upp
i versioner V5/V6/V7 i detta dokument; versionerna utgör historik och tidigare
implementationer, men det aktuella dokumentet beskriver den gällande lösningen
som en helhet.

## 2. Systemansvar och arkitektur

Lösningen består av:

- en beräkningsmotor för omplanering,
- en Windows-grafisk app (Tkinter / desktop),
- Excel- och SQL-lägen som indata,
- lokala användarinställningar och SQL-konfiguration,
- SQL-adaptrar för inläsning, uppdatering och resultatskrivning,
- exporter för Excel och CSV,
- tests för regler, UI, SQL-konfiguration och SQL-säkerhet.

Det viktigaste designkravet är att beräkning och SQL-skrivning separeras.
Appen får inte skriva till SQL bara genom att ansluta, läsa eller beräkna. Resultat
skrivs bara efter en tydlig bekräftelse i användarflödet.

Alla ändringar ska följa följande principer:

1. Fortsätt med redan etablerad affärslogik och business-rules.
2. Separera körningsmotor från UI.
3. Behandla SQL-lösenord som session-lokalt, inte som sparad konfiguration.
4. Vanliga datafel ska loggas tydligt och rapporteras utan att exponera hemliga värden.
5. Ändringar i regler eller dataflöde ska dokumenteras i det här dokumentet.

## 3. AI:ns ansvar och arbetssätt

Innan en ändring görs ska följande alltid fastställas:

1. vilka datafält som faktiskt finns i källan,
2. vilka hårda begränsningar som styr planeringen,
3. hur låsning och kapacitet fungerar,
4. hur status, försening och kundpolicy beräknas,
5. vilka SQL-tabeller, exportfiler eller användarinställningar som berörs,
6. vilka tester som krävs för att verifiera ändringen.

Följande gäller för alla ändringar:

- använd inte gissade värden för saknad eller korrupt data,
- rapportera motstridig eller ofullständig indata uttryckligt,
- skilj mellan affärsregel, implementerad lösning och tidigare historik,
- dokumentera konsekvenser för Excel-läge, SQL-läge, UI, export och databas.

## 4. Indata, källsystem och normalisering

Planeringen förutsätter att produktion, leveransdatum, maskin- och kalenderdata
finns i åtminstone ett av följande format:

- Excel-fil med fördefinierade flikar och kolumner.
- SQL Server-tabeller i approved databas.

Huvuddata som används i omplaneringen är normalt:

- `OrderNr` / AO-nummer
- `ProdGr` / produktionsgrupp
- `ArtNr` / artikelnummer
- `Op10` / operation 10
- `OrdBerLevDat` / leveransdatum
- `status` och färgstatus
- `stalltid`, `stycktid`, `kotid`
- kalender- och maskinkapacitet
- prioritet och kund-/ordervikter

Grundregler:

- Endast operation 10 får flyttas.
- Operationer som redan är påbörjade eller låsta får inte hanteras som flyttbara.
- `ProdGr` ska normaliseras så att samma logiska grupp inte behandlas som två olika grupper på grund av formatvariant.
- Datum och tid konverteras konsekvent i svensk lokal tid.
- Saknad eller ofullständig information får inte ersättas med osäkra antaganden.
- Kalendern styr faktisk tillgänglig arbetstid; operationer som inte ryms i ett pass fortsätter i nästa tillgängliga pass.
- Originalfärger och status från Jeeves bevaras separat och skrivs inte över av AI-beräkningen.

## 5. Planeringsregler och affärslogik

### 5.1 Planeringspopulation

En order får bara flyttas om den:

- ingår i den godkända planeringspopulationen,
- är operation 10,
- har giltiga data för leverans, tid, maskin och kalender,
- inte redan är låst eller avvisad på grund av ofullständiga data.

### 5.2 Låshorisont

Låshorisont är ett skydd mot att flytta redan påbörjade eller nära påbörjade
operationer. För alla körningar gäller att:

- start tidigt än `NOW + lock_horizon_hours` är låst,
- exakt gräns räknas som låst,
- `0` stänger av framtida låshorisont men lämnar redan påbörjade operationer låsta,
- ogiltiga värden faller tillbaka till standardvärdet snarare än att accepteras.

### 5.3 Fysiska och kapacitetsbegränsningar

- en produktionsgrupp kan inte köra överlappande operationer samtidigt,
- en operation kan bara fås att köras på tillåten maskin eller godkänd alternativ grupp,
- operationer måste passa i tillgängliga arbetspass,
- överlappande eller ofysisk plan mäts och rapporteras,
- redan låsta block ska bevaras som fasta kapacitetsblock,
- om en operation inte kan flyttas utan att bryta mot kapacitetsvillkor ska den förbli på ursprunglig plats.

### 5.4 Status och försening

Status baseras på marginal mellan leveransdatum och beräknad sluttid.
Det finns en tydlig separation mellan:

- status (grön/gul/röd),
- faktisk försening,
- resultatets färgstatus från ursprunglig Jeeves-data.

Regeln är:

```text
marginal = leveransdatum - beräknad sluttid
Grön: marginal > 1 dag
Gul: marginal = 1 dag
Röd: marginal < 1 dag
```

Faktisk försening beräknas som `max(0, avslutstid - förfallodatum)` i
kalenderdagar. Status och försening är olika begrepp: en order kan vara Röd utan
att vara sen, eller sen men fortfarande inom sitt tak. Det finns inga
ospecificerade gissningar för saknat leveransdatum; saknad data leder till att
operationen antingen fryses i dagens plan eller exkluderas med en förklaring.

### 5.5 Kundkonfiguration och kundvikt

Valfri `CustomerConfig` styr kundprioritet och kundspecifika förseningstak:

| Kolumn | Betydelse och validering |
|---|---|
| `OrderNumber` | Ska matcha baslinjens `OrderNr` efter uttrycklig normalisering. |
| `Customer` | Kundidentitet; tomt värde ignoreras med varning. |
| `Vikt` | Ändligt tal större än 0; saknad eller okänd kund får vikt 1. |
| `MaxLate` | Ändligt, icke-negativt antal kalenderdagar; tomt värde ger generell maxförsening. |

Regler:

- Varje `OrderNumber` ska ha en entydig policy; motstridiga dubbletter stoppar körningen.
- Konfigurationsorder som saknas i baslinjen, baslinjeorder utan konfiguration
  och antal matchade nycklar rapporteras.
- En policy som inte matchar `OrderNr` får inte kopplas via `AoNr` eller gissning.
- Har en AO flera kundorder används högsta kundvikt och lägsta ifyllda kundtak;
  alla matchade kundorder redovisas.
- Kundvikt påverkar prioritet och poäng, aldrig fysisk kapacitet.
- `CustomerConfig` och källflikar skrivs aldrig om av lösningen.

### 5.6 Poängtrappa

Poängtrappan anger hur allvarlig en avvikelse från leveransdatum är. Varje rad
är ett intervall av dagar relativt leveransdatum med en fast poäng. Positiva
dagar betyder försening, negativa dagar betyder att ordern blir klar före
leveransdatum. Orderns poäng multipliceras med kundvikten först efter att
intervallet valts.

Beräkning:

- dagar = avslutstid − leveransdatum i kalenderdagar, med tecken,
- sena dagar avrundas uppåt till hela dagar före intervallval (1,2 dagar
  räknas som 2); tidiga dagar räknas i hela dagar (4,5 dagar tidigt = −4),
- dagar före trappans första rad får första radens poäng. En trappa som börjar
  på 0 eller lägre ger därför alla tidiga order samma poäng som dag 0, vilket
  motsvarar att tidigt klar räknas som 0 dagar,
- båda ändpunkterna ingår, så dag 10 hör till ett intervall `10–obegränsat`.

Tidighetsrader (rader där Till < 0) används när order inte ska bli klara
alltför långt före leveransdatum. De påverkar körordningen: motorn föredrar en
ordning där sådana order blir klara närmare leveransdatum. Tidighetspoängen
håller aldrig tillbaka en order på en ledig maskin; planeringen placerar
fortfarande varje order så tidigt som kapaciteten tillåter. Maxförsening,
förseningsstaket och statistik över försening påverkas inte av tidighet.

Valideringsregler som måste vara uppfyllda innan trappan används:

1. Alla gränser är heltal och alla poäng är ändliga, icke-negativa tal.
2. Raderna ligger i stigande ordning. Inmatningsordningen är betydelsefull;
   motorn sorterar inte om tyst.
3. Raderna är sammanhängande: nästa rads Från = föregående rads Till + 1.
   Glapp och överlapp är förbjudna.
4. Dag 0 måste ingå, dvs. första radens Från ska vara 0 eller lägre.
5. Endast sista raden får ha tomt Till (obegränsat), och sista raden måste ha det.
6. Varje tidighetsrad (Till < 0) ska ha lägre poäng än alla rader som innehåller
   förseningsdagar (Till ≥ 1 eller obegränsat). Annars kan motorn hellre försena
   en order än låta den bli tidig.

Valideringsfel ska ange radnummer och vad som förväntades, till exempel
"Rad 7: Från (-99) ska börja direkt efter rad 6:s Till – förväntat …", så att
användaren kan rätta trappan utan att tolka tekniska meddelanden.

Standardtrappa:

| Från dag | Till dag (inklusive) | Fast poäng |
|---:|---:|---:|
| -99 | 0 | 1 |
| 1 | 2 | 2 |
| 3 | 4 | 4 |
| 5 | 7 | 9 |
| 8 | 9 | 10 |
| 10 | Obegränsat | 20 |

Den använda trappan sparas som en del av körningens policy och redovisas i
sammanfattningen; i SQL-körloggen lagras den som `ScoreBandsJson`.

### 5.7 Maxförsening

Generell maxförsening är 10 kalenderdagar som standard. Ifyllt kund-`MaxLate`
ersätter den generella gränsen; vid flera kunder gäller lägsta taket. Taket är
absolut faktisk försening, inte tillåten ökning mot originalplanen. Om
originalplanen redan överskrider taket får ordern inte bli sämre:

```text
tillåten försening = max(tillämpligt tak, försening i originalplanen)
```

### 5.8 Målordning

Målen är lexikografiska; ett lägre mål får aldrig försämra ett högre:

1. Följ hårda data-, låsnings-, maskin-, kalender-, operations- och materialregler.
2. Håll varje order inom tillämpligt tak och skydda order som redan ligger över
   taket från ytterligare försämring.
3. Maximera summan av kundvikter för Gröna order.
4. Minimera summan av kundvikt × intervallpoäng.
5. Minimera största individuella försening och undvik onödig tidighet.
6. Minska ställtid, maskinbyten och planändringar när högre mål är oförändrade.

### 5.9 Sekvensering, reparation och determinism

- EDD (`OrdBerLevDat`) är grundordning för flyttbara order per `ProdGr`, med
  stabila tie-breakers: uttrycklig prioritet om den finns, ursprunglig start
  och AO-identitet.
- Artikelklustring (samma `ArtNr`) är underordnad leveransprecision. Den får
  bara ske inom klusterfönstret, när den sparar verklig ställtid och inte
  försämrar högre mål. En order med noll ställtid dras inte fram enbart för klustring.
- Alternativmaskiner får endast vara godkända maskiner och bedöms mot
  målmaskinens kalender och effekten på båda maskinköerna.
- Vid takbrott eller oplanerad order låses berörd order lokalt till sin
  ursprungliga plats och övriga order planeras om. Kvarstår problemet avvisas
  kandidaten och hela originalplanen återställs. Kandidatfel, lokal reparation
  och säkerhetsåterfall redovisas var för sig.
- Efter varje accepterad ändring uppdateras tider, status, försening, poäng och
  kapacitetsbeläggning.

Innan resultatet levereras kontrolleras att:

- alla kvalificerade order är planerade eller har en uttrycklig orsak,
- inga planerade maskinintervall överlappar,
- arbetstid ryms inom kalender och operationsordning,
- frysta rader är oförändrade,
- tak och mål är uppfyllda,
- prioritet/rang speglar faktisk körordning, inte enbart leveransdatum.

Motorn är heuristisk. Den får aldrig påstå global optimalitet eller bevisad
omöjlighet; ett återfall till originalplanen bevisar inte att en bättre plan saknas.

## 6. Appens flöde och användningsmodell

Appen är ett Windows-skrivbordsverktyg med två datakällor: Excel och SQL Server.
Gränssnittet är uppdelat i numrerade sektioner som speglar arbetsordningen:

1. **Datakälla** – Excel-arbetsbok eller SQL Server.
2. **Planeringsparametrar** – klusterfönster (dygn), låshorisont (timmar) och
   maxförsening (kalenderdagar), var och en med enhet och en kort förklaring i
   klartext.
3. **Poängtrappa** – redigerbara rader med Från dag, Till dag och Poäng.

Under sektionerna finns körknappen, SQL-skrivknappen, knappar för att öppna
resultatfiler och nyckeltal. Flikarna visar körlogg, sammanfattning, resultat
per order och anmärkningar.

UI-texter ska vara pedagogiska och skrivna för planerare, inte för utvecklare:

- varje fält och knapp har en hjälptext (tooltip) som förklarar vad värdet
  betyder, vilken effekt det har och om något skrivs till databasen,
- rubriker och knappar numreras efter arbetsordning,
- felmeddelanden säger vad som är fel, var det är fel och hur det rättas.

### 6.1 Excel-läge

1. Välj arbetsbok (`.xlsx`) och utkatalog.
2. Kontrollera planeringsparametrar och poängtrappa.
3. Kör omplanering.
4. Granska sammanfattning, resultat och anmärkningar.
5. Resultatet sparas som nya tidsstämplade Excel- och CSV-filer. Den valda
   arbetsboken ändras inte och inget skrivs till SQL.

### 6.2 SQL-läge

1. **① Anslut** – användaren anger endast SQL-lösenordet. Appen ansluter med
   förkonfigurerad server, databas, användarnamn och ODBC-drivrutin. Inget läses
   eller ändras.
2. **② Uppdatera källdata via procedur** (valfritt) – kör den godkända
   uppdateringsproceduren efter bekräftelse, se avsnitt 8.
3. **③ Läs tabeller från SQL** – läser planeringsunderlaget. Inget skrivs.
4. **④ Kör omplanering** – beräkningen sker lokalt och lokala Excel/CSV-filer skapas.
5. **⑤ Bekräfta och skriv till SQL** – resultatet skrivs först efter granskning
   och en separat bekräftelse, se avsnitt 9.

Flödet är avsiktligt uppdelat för att förhindra oavsiktliga databasändringar.

### 6.3 Redigering av poängtrappan

- **+ Lägg till** delar sista (obegränsade) raden: den får ett slut och en ny
  obegränsad rad läggs till efter.
- **▲ / ▼** flyttar en rad uppåt eller nedåt.
- **−** tar bort en rad och sluter luckan mot grannraden. Minst en rad måste finnas kvar.
- **⇅ Sortera och rätta** sorterar raderna efter Från dag och tömmer Till på
  sista raden. Tidighetsrader behålls. Glapp, överlapp och för höga
  tidighetspoäng rättas inte automatiskt; de visas med radnummer så
  att användaren tar ett medvetet beslut.
- Trappan valideras vid körning. Vid fel stoppas körningen med ett
  radspecifikt meddelande och ett tips om Sortera och rätta.

## 7. SQL-konfiguration, autentisering och säkerhet

SQL-läge kräver:

- Microsoft ODBC Driver 18 for SQL Server,
- `pyodbc` (ingår i den paketerade appen),
- en administratörskonfigurerad `connection.json` per användare,
- ett SQL-lösenord som anges vid körning.

Lösenordet:

- lagras aldrig i `connection.json` eller `settings.json`,
- hålls endast i minnet under sessionen,
- loggas aldrig och ersätts med `<redacted>` i fel- och loggmeddelanden.

Per-användarkonfigurationen ligger i:

```text
%APPDATA%\VarnamoFinplaneringAI\V8\connection.json
```

| Nyckel | Betydelse |
|---|---|
| `server_name` | SQL Server-instans, t.ex. `tcp:server,1433`. |
| `database` | Databas med käll- och resultattabeller. |
| `username` | SQL-användare; lösenordet anges i appen. |
| `odbc_driver` | Exakt drivrutinsnamn, normalt `ODBC Driver 18 for SQL Server`. |
| `encrypt` | `yes`/`no`; kryptering av anslutningen. |
| `trust_server_certificate` | `yes` krypterar men verifierar inte servercertifikatet. |
| `connection_timeout` | Sekunder för att etablera anslutning. |
| `query_timeout` | Sekunder per fråga vid läsning och resultatskrivning. |
| `refresh_procedure` | Tvådelat `schema.procedure`-namn, eller tomt för att stänga av steg ②. |
| `refresh_parameters` | Lista med namngivna, bundna procedurparametrar. |
| `refresh_timeout` | Sekunder för uppdateringsproceduren. `0` (standard) = vänta tills SQL Server svarar. |

Regler:

- Nya konfigurationsfiler får lösningsägarens standardvärden från
  `service/config_v8.py`. Befintliga lokala filer skrivs aldrig över; saknade
  nycklar, till exempel `refresh_timeout` i äldre filer, får standardvärdet.
- Värden valideras vid start; ogiltiga värden (t.ex. negativ timeout) stoppar
  SQL-läget med ett tydligt meddelande.
- `trust_server_certificate=yes` är en kompatibilitetslösning när certifikatkedjan
  inte är betrodd. När kedjan är korrekt ska värdet vara `no`.
- `refresh_procedure` får bara aktiveras när databasägare och verksamhet
  godkänt proceduren och dess sidoeffekter.
- Behörigheter begränsas till läsning av nödvändiga källor och, när det är
  godkänt, `EXECUTE` på uppdateringsproceduren och `INSERT` i resultattabellerna.

## 8. Uppdateringsprocedur (refresh)

Uppdateringsproceduren hämtar färsk källdata (t.ex. från Jeeves) före inläsning.
Den ska:

- köras först efter en bekräftelsedialog som förklarar commit, väntetid och avbrott,
- anropas med validerat `schema.procedure`-namn och bundna parametrar,
  aldrig med sammansatta SQL-strängar,
- ogiltigförklara tidigare inläst källdata och tidigare plan, även vid fel.

Väntan och tidsgräns:

- Med `refresh_timeout = 0` väntar appen tills SQL Server svarar, oavsett hur
  länge proceduren tar. Ett positivt värde är en uttrycklig tidsgräns i sekunder.
- `refresh_timeout` gäller bara proceduren. Läsning och resultatskrivning
  använder fortsatt `query_timeout`.
- Tidsgränsen sätts på anslutningen innan proceduranropets cursor skapas och
  återställs efteråt.

Under körning visar appen en väntindikator, aktuell fas, förfluten tid och
vilken tidsgräns som gäller. Indikatorn bevisar inte databasframsteg och visar
aldrig påhittad procent.

SQL-meddelanden (`PRINT` och informationsmeddelanden) samlas in och loggas när
ODBC-anropet returnerar. De visas alltså efter att proceduren svarat, inte i
realtid. Klarstatus kräver att commit har returnerat.

Avbrott:

- Knappen **■ Avbryt procedur** är aktiv endast medan proceduren körs.
- Efter bekräftelse begär appen avbrott av den pågående SQL-satsen och
  därefter rollback.
- Proceduren kan ha gjort egna interna commits innan avbrottet; dessa kan inte
  rullas tillbaka av appen och måste kontrolleras i SQL innan nytt försök.
- Avbrott rapporteras separat från timeout och andra SQL-fel.

Om `EXECUTE` nekas är det en behörighetsfråga i SQL Server, inte ett appfel.
Vid timeout eller fel görs ingen automatisk omkörning.

## 9. SQL-resultatskrivning

Resultatskrivning sker i ett separat steg efter beräkning och granskning och
kräver uttrycklig bekräftelse. Skrivningen:

- sker i en transaktion,
- lägger till en ny körning med nytt `RunId` i `dbo.tblAIAnglysisRun`,
- skriver resultatrader med samma `RunId` i `dbo.tblAIAnglysisGetAoColorCodeList`,
- raderar eller skriver aldrig över tidigare körningar,
- rullas tillbaka helt vid fel.

Anslutning, läsning och beräkning skriver aldrig till databasen. Om servern
eller databasen i konfigurationen ändrats sedan data lästes stoppas skrivningen.

## 10. Export, filer och användarinställningar

Varje körning exporterar lokalt:

- en Excel-fil med planeringsresultat och sammanfattning,
- en CSV-fil med resultat per order,
- tidsstämplade filnamn i vald utkatalog, så att tidigare körningar inte skrivs över.

Användarinställningar sparas per användare i:

```text
%APPDATA%\VarnamoFinplaneringAI\V8\settings.json
```

Innehåll: senaste arbetsbok och utkatalog, klusterfönster, låshorisont,
maxförsening och poängtrappa. Lösenord sparas aldrig.

Sparande:

- **💾 Spara inställningar** sparar direkt och bekräftar för användaren.
- Inställningarna sparas också automatiskt vid anslutning, vid körning och när
  appen stängs.
- Varje fält valideras separat. Ett ogiltigt fält behåller sitt tidigare
  sparade värde medan giltiga fält sparas; användaren informeras om vilka fält
  som inte sparades (delvis sparat).
- Filen skrivs atomärt så att en avbruten skrivning inte förstör tidigare
  inställningar.
- **Återställ standardvärden** återställer parametrar och poängtrappa efter
  bekräftelse; sökvägar behålls.
- Inställningar och `connection.json` bevaras vid uppgradering och avinstallation.

## 11. Felhantering och loggning

Felhanteringen ska:

- ersätta lösenord med `<redacted>`,
- ange vilken operation som misslyckades (`connect`, `refresh`, `load`, `write`),
- skilja på avbrott, timeout, behörighetsfel och klient- eller datafel,
- förklara konsekvensen: vad som rullats tillbaka, vad som ogiltigförklarats
  och vad användaren behöver kontrollera,
- vid timeout eller avbrott av proceduren tydligt säga att utfallet inte är
  bekräftat och att interna commits och sidoeffekter ska verifieras i SQL,
- vid poängtrappefel ange radnummer och föreslagen åtgärd,
- aldrig exponera hemliga värden.

## 12. Resultat, spårbarhet och kontroll

Resultatet bevarar källvärden, mallens kolumnnamn och ordning samt lägger till
AI-fält. `AI_OpkoPrioritet` härleds från faktisk startordning per `ProdGr` efter
planeringen och ändrar inte frysta rader. Radkommentarer förklarar på svenska
beslut, frysningsorsak, ursprunglig och ny maskin, påverkan på status och
försening, kundpolicy, klustring eller omruttning, reparation och datavarningar.

Sammanfattningen jämför samma population före och efter, med samma
statusdefinition, och innehåller:

- orderantal, planerade och oplanerade order med skäl,
- Grön/Gul/Röd-fördelning samt Jeeves originalstatus separat,
- total och största faktiska försening, antal försämrade order,
- kundviktad poäng och viktad grönprioritet,
- takutfall, order över tak i originalplanen, kvarstående överskridanden och
  säkerhetsåterfall,
- frysta order per orsak, omruttningar, klustringar, sparad ställtid och planändringar,
- alla policyvärden som användes, inklusive `NOW_Stockholm`, låshorisont,
  maxförsening och poängtrappa.

## 13. Testning, risker och acceptanskriterier

Tester ska täcka:

- låshorisont före, vid och efter gräns, noll och decimalvärden,
- fasta block, kalenderpass, kapacitet, EDD, klustring och alternativmaskin,
- status kontra försening, avrundning och precision,
- lokalt tak, fullständigt säkerhetsåterfall och kundmatchning, dubbletter, vikt och kundtak,
- poängtrappans validering med radspecifika fel, flytt av rader och Sortera och rätta,
- SQL-anslutningssträng, konfigurationsvalidering inklusive `refresh_timeout`,
- att proceduren väntar enligt `refresh_timeout`, kan avbrytas, rullar tillbaka
  och släpper cursor,
- att lösenord aldrig hamnar i inställningar, konfiguration eller loggar,
- att procedur- och parameternamn valideras och värden binds,
- att SQL-skrivning kräver bekräftelse och rullas tillbaka vid fel,
- delvis sparande av inställningar.

Excel- och SQL-läge ska ge samma kundpolicy och poängresultat för samma
validerade indata.

Särskilt rapporterbara risker:

- `ProdGr`- eller ordernycklar med blandade typer och format,
- felaktiga Excel-serienummer eller blandade tidszoner,
- saknat `OrderNr`/`OrdBerLevDat`, opålitliga Op10-tider eller saknad kalender,
- låsta block som redan överlappar,
- okänd eller motstridig kundpolicy,
- order som redan i originalplanen överskrider taket,
- en uppdateringsprocedur med interna commits eller externa sidoeffekter,
- att ett heuristiskt återfall tolkas som bevis på omöjlighet.

Använd syntetiska testdata. Kundutdrag och hemligheter får inte förekomma i
prompter, dokumentation, testfixturer eller loggar.

## 14. Paketering och release

- Appen byggs med PyInstaller och paketeras som Windows-installerare med Inno Setup.
- Release byggs manuellt via GitHub Actions-arbetsflödet för V8, som kör
  testerna, bygger installeraren och publicerar den som artefakt/release.
- Installationen kräver administratörsrättigheter. Om företagets säkerhetspolicy
  blockerar installationen hanteras det av IT (signering, undantag eller central distribution).
- Excel-läget kräver ingen SQL-drivrutin; SQL-läget kräver Microsoft ODBC
  Driver 18 for SQL Server på klientdatorn.
- Detaljer om installation, administratörskonfiguration och behörigheter finns
  i `README_v8.md`; användarflödet beskrivs i `documentation_v8.html`.

## 15. Avgränsningar och antaganden

- Motorn är heuristisk och garanterar inte global optimalitet.
- Källsystemets data förutsätts vara kvalitetssäkrad och följa datamodellen.
- Uppdateringsprocedurens innehåll ägs av databasägaren; appen styr bara anrop,
  väntan, avbrott och rollback.
- Planeringsresultat ska alltid granskas innan de skrivs till SQL.

## 16. Sammanfattning

Detta dokument beskriver AI Omplanering version 1 som en enhetlig lösning med
tre centrala flöden:

- Excel-läge för lokal omplanering och export,
- SQL-läge för inläsning från SQL Server med valfri, avbrytbar uppdateringsprocedur,
- SQL-resultatskrivning efter uttrycklig bekräftelse.

Ändringar i regler, dataflöden, konfiguration eller användargränssnitt ska
dokumenteras här i samma ändring.
