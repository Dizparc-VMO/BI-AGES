# AI Omplanering V7 — fullständig beskrivning och instruktion

**Version:** 7.0 | **Datum:** 2026-10-14

Det här dokumentet beskriver hela V7-lösningen: syfte, komponenter,
indataformat, planeringsregler, körning via skrivbordsapp eller SQL-tjänst,
resultat, kontroller och begränsningar. Reglerna nedan är kompletta för V7 och
kräver inte att läsaren känner till V5 eller V6. V7 har egna app-, motor-, test-
och servicefiler; V5/V6-filerna och den befintliga SQL-tjänsten ändras inte.

## Praktisk körguide

### Välj körsätt

V7 har två separata sätt att köras:

- **Skrivbordsapp** läser en Excel-arbetsbok och sparar tidsstämplade Excel- och
  CSV-resultat. Det här är det rekommenderade sättet för en användarstyrd
  engångskörning.
- **SQL-tjänst** läser planeringsunderlag och kundpolicy från SQL Server, kör
  samma V7-motor och skriver resultat och körinformation till databasen. Den
  används först efter att databasschema, anslutning och dry-run har verifierats.

Båda körsätten använder samma planeringsregler och V7-standardvärden. De har
separata konfigurations- och körmiljöer; inställningar i skrivbordsappen ändrar
inte SQL-tjänstens konfiguration.

### Kör skrivbordsappen

Kör följande från V7-projektmappen `companies/Värnamo/ai/Finplanering AI`:

```powershell
python -m pip install -r requirements.txt
python omplanering_app_v7.py
```

1. Välj arbetsboken med de fyra obligatoriska källflikarna enligt avsnittet
   **Indata och kundkonfiguration**. Lägg till `CustomerConfig` om kundspecifik
   vikt eller maxförsening ska användas.
2. Välj en utkatalog. Appen föreslår körparametrar; kontrollera låshorisont,
   generell maxförsening, poängintervall och klusterfönster innan
   körningen startas.
3. Starta omplaneringen. Följ körloggen och läs alla datavarningar,
   kundmatchningsvarningar, reparationer och säkerhetsåterfall.
4. Granska sammanfattningen och resultatraderna i appen. Öppna de skapade
   Excel- och CSV-filerna och verifiera planen mot den verkliga produktionen
   innan någon ändring förs tillbaka till Jeeves.

Appen sparar endast sina egna UI-parametrar i
`.omplanering_ui_v7.json`. Den skriver inte över arbetsboken; resultatfilerna
får tidsstämpel och suffixet `_v7_resultat_`.

Motorn kan också köras direkt från PowerShell utan GUI:

```powershell
python omplanering_core_v7.py "AI omplanering_V7.xlsx" -o output
```

Om `-o` utelämnas skapas resultat i en `output`-mapp bredvid arbetsboken.
Körspecifika motorparametrar och deras validering beskrivs i avsnitt 4 och 6.

### Kör SQL-tjänsten

SQL-tjänsten är en separat driftsättningsväg. Följ ordningen nedan och använd
endast rätt godkänd miljö:

1. Kontrollera databas, anslutning och V7-inställningar. Kör
   `service/sql/03_v7_customer_config_and_metrics.sql` mot den avsedda
   databasen efter granskning.
2. Ladda och kontrollera `dbo.CustomerConfig`; bekräfta att
   `OrderNumber`-värden matchar baslinjens `OrderNr`.
3. Kör från projektmappen:

   ```powershell
   python service/run_service_v7.py --check
   python service/run_service_v7.py --dry-run --force
   ```

4. Granska dry-run-resultat och varningar. Dry-run ska godkännas innan
   schemaläggning eller skrivning i drift.
5. Först efter godkännande får en separat V7-uppgift registreras med
   `service/install_task_v7.ps1`. Följ även instruktionerna i
   [`service/README_v7.md`](service/README_v7.md) för databasbehörigheter,
   schemaläggning och drift.

Tjänsten skriver inte till `CustomerConfig`. `--force` förbigår körgrinden och
ska användas för provkörning endast när det är avsiktligt. V7:s SQL-schema och
uppgift är separata från den befintliga tjänsten och får inte ersätta eller
ändra dess konfiguration.

### Kontrollera installationen

Kör V7:s riktade tester från projektmappen:

```powershell
python -m unittest test_omplanering_v7 -v
```

För en mer lättläst användarguide med exempel och flödesschema, öppna
[`dokumentation_v7.html`](dokumentation_v7.html). Den här instruktionen är den
fullständiga regel- och driftbeskrivningen.

## 1. Mål och prioritering

V7 ska skapa ett realistiskt förslag för Operation 10 (Op10). Målen jämförs
lexikografiskt; ett lägre prioriterat mål får inte bryta ett högre prioriterat
krav:

1. Följ låsning, maskin-, kalender- och indataregler. Gissa inte saknad data.
2. Håll varje planerad order inom dess tillämpliga maxförsening. En kundgräns
   ersätter den generella gränsen. En order som redan överskrider gränsen i
   originalplanen får inte försämras ytterligare; överskridandet rapporteras.
3. Maximera summan av kundvikterna för gröna order. Grönstatus har den
   oförändrade marginalregeln i avsnitt 3.
4. Minimera summan av kundvikt multiplicerad med orderns konfigurerbara
   förseningspoäng.
5. Minimera största individuella försening och undvik onödig tidighet.
6. Minska ställtid, maskinbyten och planändringar när högre mål är oförändrade.

Vikten gäller per AO/position efter att dess kundordrar har identifierats. Om
en AO gäller flera kunder används högsta kundvikt; den lägsta kundgränsen gäller.
Kundvikten ändrar inte maskinkapacitet eller annan fysisk begränsning.

## 2. Indata och kundkonfiguration

Arbetsboken innehåller de fyra obligatoriska V5-källflikarna:

- `tblSTGetAoColorCodeLis` — baslinje, `AoNr`, `AoPos`, `OpNr`, `OrderNr`,
  leveransdatum, färg och ursprungliga tider.
- `tblSTAllOperationsForAoNr` — operationstider, status, ProdGr och kalendernr.
- `tblSTGetDateCalenderWorkingTime` — maskinernas arbetstidskalendrar.
- `tblSTProductionGroupPrioOnItem` — godkända alternativa ProdGr.

Den valfria V7-fliken `CustomerConfig` har exakt följande kolumner:

| Kolumn | Betydelse | Regel |
|---|---|---|
| `OrderNumber` | Kundorderidentitet | Måste matcha baslinjens `OrderNr` efter normalisering. |
| `Customer` | Kundnummer eller kundnamn | Behålls som kundidentitet; tomt värde ignoreras med varning. |
| `Vikt` | Kundens relativa prioritet | Måste vara ett ändligt tal större än 0. Saknad/okänd order får vikt 1. |
| `MaxLate` | Kundens absoluta maxförsening | Kalenderdagar efter leveransdatum; ändligt tal minst 0. Tomt värde använder globalgränsen. |

Varje `OrderNumber` ska ha en enda entydig policy. Identiska dubbletter kan
slås ihop; motstridiga kund-, vikt- eller maxvärden ska stoppa körningen.
Order i CustomerConfig som saknas i baslinjen och baslinjeorder som saknar
kundrad rapporteras. Saknad CustomerConfig-flik använder vikt 1 och den
generella maxgränsen för alla order.

**Viktigt före produktionskörning:** verifiera nyckelöverlappet mellan
`CustomerConfig.OrderNumber` och `tblSTGetAoColorCodeLis.OrderNr`. Om ingen rad
matchar får orderna standardvikt och generell maxgräns; V7 får inte gissa en
koppling via `AoNr`.

När samma AO/position omfattar flera CustomerConfig-order används samtliga
matchade kundorder i spårbarheten, högsta `Vikt` och lägsta `MaxLate`. Baslinjens
leveransdatum styr fortfarande AO-radens status och poäng; om kundordrarna har
olika leveransdatum måste underlaget granskas så att den valda AO-leveranstiden
är korrekt.

SQL-tjänsten läser motsvarande källtabell `dbo.CustomerConfig` med samma fyra
kolumner. Den skriver inte kundkonfigurationen.

## 3. Datum, status och försening

Alla datum normaliseras före beräkning. Excel-serienummer, datum/tider,
`ProdGr` och orderidentiteter normaliseras uttryckligen. `NOW_Stockholm` bestäms
en gång per körning. Jämförelser av faktisk försening använder kalenderdagar
med deldagsprecision:

```text
tardiness = max(0, beräknad sluttid − leveranstid) i kalenderdagar
```

Färgstatus är separat från faktisk försening och använder marginal i hela
kalenderdatum:

- Grön: marginal större än `GREEN_MARGIN_DAYS` (standard 1 dag).
- Gul: marginal exakt `GREEN_MARGIN_DAYS`.
- Röd: marginal mindre än `GREEN_MARGIN_DAYS`.

En order som blir klar på leveransdagen har 0 tardiness men är Röd. Jeeves
`ColorName` bevaras och visas separat från den jämförbara AI-statusen.

## 4. Dynamisk förseningspoäng

Poängtrappan består av ett eller flera sammanhängande, icke överlappande
heltalsintervall med fast poäng per order. Faktisk försening avrundas uppåt
till hela kalenderdagar innan intervallet väljs. Båda intervalländpunkterna
ingår. Poängen beräknas per order, multipliceras med kundvikten och summeras:

```text
kundviktad orderpoäng = Kundvikt × fast poäng för intervallet
```

Standardintervallen är:

| Från dag | Till dag (inklusive) | Fast poäng |
|---:|---:|---:|
| -99 | 0 | 1 |
| 1 | 2 | 2 |
| 3 | 4 | 4 |
| 5 | 7 | 9 |
| 8 | 9 | 10 |
| 10 | Obegränsat | 20 |

Intervallen måste täcka dag 0 till obegränsat utan luckor eller överlapp. Det
sista övre värdet lämnas tomt i appen. Poängen ska vara ändliga och icke-
negativa. Desktopinställningar använder `score_bands`; SQL-konfigurationen
använder `TARDINESS_SCORE_BANDS`. CLI-flaggan `--score-band` kan upprepas med
formatet `FRÅN:TILL:POÄNG` och `*` som obegränsad övre gräns.

Exempel:

- En försening på 1,2 dagar avrundas till dag 2 och får poängen 2 före viktning.
- Volvo med vikt 10 och 10 dagars försening får `10 × 20 = 200` poäng.
- Scania med vikt 5 och 10 dagars försening får `5 × 20 = 100` poäng.

`stycktid` används endast för kapacitetsberäkning. Den multiplicerar inte
kundvärde eller poäng.

## 5. Generell och kundspecifik maxförsening

Den generella maxförseningen är ett körningsvärde, föreslaget standardvärde
**10 kalenderdagar**. Kundens `MaxLate`, när det finns och är ifyllt, ersätter
det generella värdet för den kunden. Vid flera kunder på samma AO gäller den
lägsta kundgränsen.

För order `i` gäller:

```text
effektivt tillåten tardiness = max(tillämplig maxgräns, originalplanens tardiness)
```

Den andra termen är ett skydd för redan sena order: om originalet redan ligger
över gränsen får V7 behålla eller förbättra originalet, men får inte göra ordern
mer försenad än originalet. Sammanfattningen visar både antal order som låg
över gränsen i originalet och antal över gränsen efter planeringen.

Gränsen är absolut tardiness efter leveransdatum, inte ett tillåtet antal dagar
ökning utöver originalplanen. Gräns och poäng är separata: gränsen avgör vad
som är tillåtet; poängen väljer mellan tillåtna planer.

Om en kandidat överskrider effektivt tillåtet tak eller lämnar flyttbar order
oplanderad låses berörd order till originalslotten och resten schemaläggs om.
Om problem kvarstår efter lokal reparation avvisas kandidaten och hela
originalplanen återställs. Återfall bevisar inte att en bättre plan saknas.

## 6. Hårda planeringsregler

- Ordinarie population är AO som finns i baslinje och operationsunderlag.
- Endast `OpNr = 10` får flyttas. Status måste vara 0.
- Leveransdatum, ursprunglig start, positiv Op10-varaktighet och användbar
  kalender måste finnas. Saknad varaktighet eller kalender får inte gissas.
- En Op10 får flyttas endast om ursprunglig start är senare än
  `NOW_Stockholm + lock_horizon_hours`. Standardhorisont är 4 timmar; exakt
  gränstid är fryst. Decimaler och noll tillåts. Noll tar inte bort lås för
  redan startade operationer, status eller saknad data.
- Frysta Op10-operationer behåller originalstart, originalslut och ProdGr och
  reserveras som fasta kapacitetsblock. Ursprungliga överlapp rapporteras.
- En ProdGr kör inte två Op10 samtidigt. Arbetstid måste rymmas i angivna
  kalenderfönster och skift. Ingen extrapolering görs efter känd täckning.
- `EDD` är grundordning. Godkända alternativa maskiner hämtas från
  `tblSTProductionGroupPrioOnItem`; deras kalendrar och berörda maskinköer
  kontrolleras. Högst fyra ruttpass utförs.
- Samma artikel kan klustras inom `CLUSTER_WINDOW_DAYS` (standard 30) när det
  sparar verklig ställtid. Klustring är underordnad maxgräns och kundviktade mål.
- Planerad sluttid efter flyttad Op10 beräknas genom att samma tidsförskjutning
  förs vidare enligt befintlig V5/V6-modell. Material och bemanning kan endast
  kontrolleras om sådana data finns i underlaget; de får inte antas.

## 7. Utdata och spårbarhet

Resultat innehåller ursprungliga fält och V7-förslag. Excel/CSV lägger till
`KundOrderNr`, `Kundnr`, `Kundvikt`, `MaxFörseningsdagar`, ursprunglig och AI-
förseningspoäng samt `AI_CapExcessDygn`. Kommentarer anger kundpolicy,
frysningsorsak, omruttning, klustring, status och reparation.

Sammanfattningen ska redovisa:

- antal gröna/gula/röda före och efter samt kundviktad grönprioritet,
- total och kundviktad förseningspoäng före/efter och använda poängintervall,
- generell maxförsening, befintliga och kvarvarande order över angivet max,
- takreparationer, säkerhetsåterfall, oplanerade order och kundkonfigurations-
  varningar,
- använd låshorisont, klusterfönster, körtid och datakonflikter.

Excelresultat har tidsstämpel och `_v7_resultat_` i filnamnet. Kundfliken
`CustomerConfig` bevaras oförändrad. SQL-resultat länkas till körning via
`RunId`; körparametrarna lagras i V7:s SQL-körlogg.

## 8. Kvalitetskrav och tester

Före godkännande ska tester täcka:

1. Standardintervall, anpassade intervall, avrundning uppåt av deldagar,
   inkluderade ändpunkter, nollpoäng och validering av glapp/överlapp.
2. Kundviktning av grönprioritet och poäng; operationstid får inte påverka vikt.
3. Globalt tak, kundtak, blankt tak, okänd kund och AO med flera kunder.
4. Originalorder över gränsen, tillåten förbättring och förbjuden försämring.
5. Lokal reparation, kvarstående fel och fullständigt säkerhetsåterfall.
6. V6-låshorisont, kalender, fasta block, alternativmaskin och export.
7. Excel och SQL ska använda samma CustomerConfig-regler och spara policy i
   separata V7-inställningar.

V7 är en heuristik, inte en fullständig matematisk optimeringslösare. Ett
förslag är inte ett bevis på global optimalitet eller att alla fysiska villkor
är uppfyllda. Granska varningar, verklig maskinbeläggning, material och
operationsberoenden före frisläppning till produktion.

Start: [README_v7.md](README_v7.md). SQL-schema: `service/sql/03_v7_customer_config_and_metrics.sql`.