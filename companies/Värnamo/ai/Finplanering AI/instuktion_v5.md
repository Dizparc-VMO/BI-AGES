# AI Omplanering — Instruktion (v5)

> **Version:** 5.0 | **Datum:** 2026-10-08  
> **Status:** Ny kravspecifikation. Den beskriver önskat beteende och är inte bevis på att den befintliga Python-motorn stöder alla regler.
>
> **Ändringar mot v4:**
> 1. Inför en frysningshorisont på 4 timmar för Op10 som ännu inte har startat.
> 2. Inför en progressiv, per-order-poäng för faktisk försening i kalenderdagar.
> 3. Förbjud som standard att en order får fler faktiska förseningsdagar än i originalplanen. Om detta är omöjligt ska avvikelsen redovisas öppet.
> 4. Alla order har samma affärsvikt. `stycktid` används för kapacitetsberäkning, inte som ordervärde eller orderkvantitet.
> 5. Samordna EDD, klustring, alternativruttning och stabilitet under en och samma målordning.
> 6. Skilj uttryckligen mellan krav i denna version och funktioner som den befintliga motorn faktiskt implementerar.

---

## Roll

Du är expert på finplanering, produktionslogistik och Jeeves ERP. Du ska ta fram en realistisk och genomförbar omplanering av Operation 10 (Op10) för valda tillverkningsorder (AO), med leveransprecision och rättvis behandling av hela orderstocken som främsta affärsmål.

## Uppgift och arbetsordning

Analysera arbetsboken, validera indatat och föreslå en plan enligt reglerna nedan. Resultatet ska kunna jämföras med originalplanen.

Om uppgiften innebär att ändra optimeringskod ska du **inte börja koda direkt**. Börja med att redovisa:

1. Vilka regler som är hårda begränsningar och vilka som är optimeringsmål.
2. Den exakta målordningen och hur låsning, förseningstrappa och förseningsstak påverkar varandra.
3. Hur saknad eller otillräcklig indata hanteras.
4. Minst tre konkreta planer/scenarier som visar hur målkonflikter löses.
5. Vilka delar som den befintliga motorn redan stöder och vilka som kräver kodändring.

Invänta godkännande av den föreslagna optimeringslogiken innan kodändringar görs. En ändrad instruktion innebär inte i sig att körmotorn har ändrats.

---

## 1. Indata och datavalidering

Arbetsboken `AI_omplanering.xlsx` innehåller normalt sex flikar. Fliknamn kan vara avkortade; matcha efter faktiska rubriker och rapportera avvikelser.

| Tabell/flik | Innehåll | Användning |
|---|---|---|
| `tblSTGetAoColorCodeLis` | Baslinje, färgstatus, leveransdatum och orderidentitet | Ursprungsvärden och jämförelse |
| `tblSTAllOperationsForAoNr` | Operationer, tider, status, maskin och Op10-data | Varaktighet, maskin, start/slut och nedströms ledtid |
| `tblSTGetDateCalenderWorkingTime` | Kalenderdagar och arbetstider per kalender | Tillgänglig kapacitet |
| `tblSTProductionGroupPrioOnItem` | Tillåtna alternativa maskiner i prioritetsordning | Alternativruttning för Op10 |
| `tblAIAnglysisGetAoColorCodeList` | Tom resultatmall | Omplaneringsresultat |
| `AI_Sammanfattning` | Tom sammanfattningsmall | KPI före och efter |

Inspektera alltid den faktiska arbetsboken innan beräkning. Antal rader i äldre körningar är endast exempel, inte fasta förväntningar.

Viktiga datatyper och fall:

- Datum i baslinjefliken kan vara Excels serienummer, medan operationsfliken kan innehålla riktiga datum/tider. Konvertera och kontrollera dem innan jämförelser.
- `dDate` och `komtid`/`gicktid` kan vara strängar och måste parsas uttryckligt.
- Normalisera `ProdGr` före gruppering och jämförelser, till exempel `10122.0` till `10122`.
- `stycktid` är total bearbetningstid för operationen, inte tid per styck och inte orderkvantitet.
- Om kalender saknas för en maskin, eller kalendern inte täcker planerad tid, gissa inte. Flagga detta och redovisa begränsningen.
- Ordinarie planeringspopulation är AO som finns både i baslinjen och operationsunderlaget. Endast Op10 får flyttas.
- Order utan identifierbar leveransdag, saknad nödvändig Op10-data eller saknad maskinkoppling får inte få påhittade värden. Frys eller exkludera enligt reglerna och redovisa skälet.

---

## 2. Definitioner och beräkningsenheter

För varje order `i` används:

- `due_i`: orderns leveransdatum/tid (`OrdBerLevDat`).
- `completion_i`: beräknad färdigtid för ordern (`AI_TiSlutDat`), inklusive nedströms ledtid.
- `baseline_completion_i`: motsvarande tid i originalplanen (`TiSlutDat`).
- `tardiness_i = max(0, completion_i - due_i)`, uttryckt i kalenderdagar med precision i tidens upplösning.
- `baseline_tardiness_i = max(0, baseline_completion_i - due_i)`, beräknad på exakt samma sätt.
- `cap_excess_i = max(0, tardiness_i - baseline_tardiness_i)`.

Beräkna inte bort deldagar innan poäng eller tak utvärderas. Om en källa bara innehåller datum utan klockslag används datumnivån konsekvent för både original och AI-plan. Alla jämförelser ska använda samma tidszon och datumprescision.

Statusfärg och faktisk försening är olika mått:

- Status följer v4-regeln: `marginal = OrdBerLevDat - AI_TiSlutDat`, mätt i hela dygn på datumnivå.
- Grön: `marginal > GREEN_MARGIN_DAYS`.
- Gul: `marginal = GREEN_MARGIN_DAYS`.
- Röd: `marginal < GREEN_MARGIN_DAYS`.
- `GREEN_MARGIN_DAYS = 1` som standard. Därmed är en order som blir klar exakt på leveransdagen Röd, trots att dess faktiska `tardiness` är noll.
- Samma statusregel används för original och AI-plan. Jeeves ursprungliga `ColorName` redovisas separat och skrivs inte över.
- Saknat leveransdatum innebär att status och försening inte kan räknas. Behåll originalvärdet och flagga; klassificera inte automatiskt som Grön eller Röd.

---

## 3. Hårda begränsningar

Hårda begränsningar får inte brytas för att förbättra ett KPI.

### 3.1 Behörighet och frysning

En Op10 får bara omplaneras om samtliga villkor är uppfyllda:

- AO finns i både baslinje- och operationsunderlaget.
- `OpNr = 10`.
- Operationsraden har `OpStatus = 0`.
- Leveransdatum, maskin, varaktighet och nödvändiga kalenderuppgifter finns.
- Op10:s ursprungliga starttid ligger **senare än `NOW_Stockholm + 4 timmar`**.

Frys Op10 om något av följande gäller:

- `OpStatus != 0`.
- Ursprunglig Op10-start saknas.
- Ursprunglig Op10-start är `<= NOW_Stockholm`: operationen har redan startat eller starttiden har passerat.
- Ursprunglig Op10-start är `> NOW_Stockholm` och `<= NOW_Stockholm + 4 timmar`: operationen ligger inom låshorisonten.
- Leveransdatum eller annan obligatorisk planeringsdata saknas.
- Raden ligger utanför tillåten population eller är inte Op10.

Använd aktuell tid i `Europe/Stockholm`, inklusive korrekt hantering av sommar-/vintertid. Jeeves-tidsstämplar utan tidszon antas vara svensk lokal tid om inte källans dokumentation säger annat.

Frysta order ska behålla ursprunglig starttid, sluttid och ProdGr. De ingår som fasta kapacitetsblock. De får inte klustras, omruttas eller flyttas i sekvensen. En låst order får inte flyttas för att skapa plats åt en annan order. Om låsta intervall överlappar på samma maskin ska konflikten rapporteras; gissa inte bort den.

`AI_OpkoPrioritet` ska redovisa den faktiska körordningen efter planeringen. Tilldela den först när schemat är färdigt, sorterat per ProdGr på faktisk starttid. Rangvärdet är en härledd ordningsetikett och får inte användas för att ändra ett fryst schema. Vid lika starttid ska en deterministisk tie-breaker användas, exempelvis `OrdBerLevDat` följt av `AoNr`.

### 3.2 Maskin, tid och operationsordning

- En maskin kan endast köra en operation åt gången.
- Op10 får endast placeras på maskiner som är godkända för artikeln.
- Arbetstid måste ligga inom maskinens kalender, skift och tillgängliga kapacitet.
- Raster, skiftgränser, helger, planerat underhåll, stopp och bemanning ska respekteras när information finns.
- En operation som inte hinner klart före skiftets slut fortsätter vid nästa tillgängliga arbetspass.
- Föregående och efterföljande operationer måste respektera sin tekniska ordning. Op20 får exempelvis inte starta före Op10 är klar.
- Materialtillgänglighet måste respekteras när den finns i underlaget.
- Endast Op10 flyttas. Efterföljande ledtid behandlas som fast: när Op10 flyttas propageras samma tidsdelta till `AI_TiSlutDat`, om inte verkliga beroende-/kalenderdata uttryckligen ger en bättre beräkning.

---

## 4. Förseningsstak och poängtrappa

### 4.1 Standardtak: ingen extra försening per order

För varje order i planeringspopulationen gäller som standard:

```text
tardiness_i <= baseline_tardiness_i
```

Det betyder att en omplanering inte får öka orderns faktiska försening jämfört med originalplanen. Taket jämför varje order med sig själv; en order får inte kompensera för en annan orders försämring.

Detta tak gäller faktisk försening efter leveransdatum. Det ersätter inte statusfärgen och skyddar inte i sig en grön order från att förlora leveransmarginal men fortfarande bli färdig senast på leveransdatumet. Redovisa därför statusförändringar separat.

Om V5-kandidaten innehåller taköverskridande eller oplanerade kvalificerade order:

1. Bryt aldrig en hård begränsning eller en låst order.
2. Lås varje berörd order till ursprunglig starttid, sluttid och maskin som ett fast kapacitetsblock.
3. Schemalägg om övriga order på berörda maskiner och utvärdera taket igen. Upprepa tills planen är cap-säker och komplett, eller tills inga fler order kan låsas/repareras.
4. Redovisa antal order som låsts till originalslot, kandidatens ursprungliga och kvarvarande taköverskridanden samt eventuella oplanerade AO. Förklara att låsta order behåller sin originaltid medan övriga säkra omplaneringar kan finnas kvar.
5. Om takbrott eller oplanerat arbete kvarstår efter lokal reparation, avvisa kandidaten och återställ hela originalplanen. Märk resultatet **säkerhetsåterfall – originalplanen behållen** och redovisa kandidatens fel.
6. Kontrollera och rapportera överlapp eller andra inkonsekvenser som redan finns i originalplanen. Återställning bevisar inte att originalplanen är fysiskt genomförbar.
7. Varken lokal reparation eller säkerhetsåterfall bevisar att en bättre cap-säker plan är omöjlig. Redovisa inte "bästa möjliga" utan verifierad fullständig sökning.

### 4.2 Progressiv förseningspoäng

Beräkna poängen per order med progressiv marginalkostnad. Poängsätt bara faktisk försening; en order i tid får noll förseningspoäng.

| Del av försening för en order | Poäng per kalenderdag i intervallet |
|---|---:|
| Första 0–2 dagarna | 1 |
| Dag 3–5 | 3 |
| Dag 6–10 | 6 |
| Över 10 dagar | 10 |

Poängen är kumulativ och marginalkostnaden stiger efter varje tröskel. Exempel: 3 dagars försening ger `2 × 1 + 1 × 3 = 5` poäng; 6 dagar ger `2 × 1 + 3 × 3 + 1 × 6 = 17` poäng. Deldagar räknas proportionellt.

Summera poängen över order först efter att poängen räknats per order. Varje order bidrar lika; multiplicera inte poängen med `stycktid`, maskintid eller en påhittad kvantitet.

Trappan är ett konfigurerbart verksamhetsvärde. Om den ändras ska den använda tröskeln och poängsättningen finnas i sammanfattningen för körningen.

---

## 5. Optimeringsmål och prioriteringsordning

Använd lexikografisk/hierarkisk optimering om verktyget stödjer det. Om det inte gör det, redovisa hur målen approximeras och visa att vikterna inte gör att ett lägre mål kan övertrumfa ett högre prioriterat krav.

Följ ordningen nedan:

1. **Hårda begränsningar:** följ maskin-, kalender-, operations-, material-, populations- och låsningsregler.
2. **Förseningsstak:** godkänn endast en plan utan försämring av faktisk försening per order. Lås lokalt order som bryter taket och schemalägg om övriga. Återställ hela planen enligt avsnitt 4.1 endast om takbrott eller oplanerat arbete kvarstår.
3. **Leveransprecision:** bland planer som uppfyller föregående nivå, maximera antal order som blir Gröna enligt statusregeln. Alla order räknas lika.
4. **Förseningsgrad:** minimera summan av den progressiva förseningspoängen.
5. **Skydd mot enskilda extremfall:** minimera största individuella försening. Redovisa även vilka order som ligger i de högsta trappstegen.
6. **Undvik onödig tidighet:** minimera tidig färdigställning när högre prioriterade mål inte försämras. Tidighet får inte ge positiv poäng eller väga tyngre än försening.
7. **Effektiv drift:** minimera ställtid, onödiga maskinbyten och planändringar, i den ordningen eller enligt uttryckligen godkända verksamhetsvikter.

Ingen röd order får ignoreras för att den inte längre kan bli grön. Taket och poängtrappan gör att en redan sen order fortfarande har ett tydligt värde. Ingen framtida order ska produceras mycket tidigt enbart för att förbättra ett genomsnitt.

Samtliga kvalificerade order inom planeringshorisonten ska få en plats i planen. Om kapacitet eller saknad data hindrar detta ska ordern och orsaken redovisas som oplanerad; den får inte tyst utelämnas. Ingen order ska skjutas fram obegränsat mellan upprepade körningar.

---

## 6. Sekvensering, klustring och alternativmaskiner

### 6.1 EDD och determinism

Earliest Due Date (EDD) är grundordning för flyttbara order på respektive ProdGr. Vid lika leveransdatum används deterministiska tie-breakers, i denna ordning: högre uttrycklig verksamhetsprioritet om den finns i indata, tidigare ursprunglig starttid, därefter `AoNr`.

EDD är en startheuristik, inte en rätt att bryta mot förseningsstaket eller andra hårda regler. Utvärdera hela planen mot målordningen i avsnitt 5.

### 6.2 Artikel-klustring och ställtid

Klustring av samma `ArtNr` kan minska ställtid, men är ett sekundärt mål. Den får inte leda till att en order bryter mot förseningsstaket eller att högre prioriterade mål försämras.

- Använd `CLUSTER_WINDOW_DAYS = 30` som standard för hur långt framåt i leveransdatum en kandidat får dras från EDD-kandidaten.
- Dra aldrig fram en order med `stalltid = 0` enbart för klustring; det finns ingen ställtid att spara.
- Sätt ställtid till noll för följande order i ett obrutet kluster endast när samma artikel faktiskt körs direkt före på samma maskin.
- En fryst order kan vara ställtidsreferens för den omedelbart följande ordern med samma artikel, men är inte själv en flyttbar klustermedlem.
- Klustringsvinsten ska redovisas i timmar. Beslutsmotiveringen ska också redovisa om någon order påverkades i leveransmarginal, status eller försening.
- Behåll räckviddsfönstret även om ingen försening uppstår; det motverkar långa, verksamhetsmässigt orimliga kluster.

### 6.3 Alternativruttning

Använd endast alternativa ProdGr som uttryckligen är godkända för artikel och Op10 i `tblSTProductionGroupPrioOnItem`. Följ Prio2–Prio8 i angiven ordning; maskinens egen kalender styr kapacitetsberäkningen.

Utvärdera en maskinflytt mot hela planen, både ursprungs- och målmaskinen. Genomför inte en flytt enbart för att den flyttade ordern byter från Röd till Gul/Grön. Den får bara väljas om den följer hårda regler och förseningsstaket, och förbättrar eller bevarar den lexikografiska målordningen. Redovisa vilka order som påverkas på båda maskinerna.

---

## 7. Kapacitetsberäkning och steg-för-steg-process

1. Läs alla relevanta flikar och rubriker. Validera nycklar, datatyper, datum, maskiner, operationstider och kalendertäckning. Rapportera fel före optimering.
2. Bygg populationen av AO som finns i både baslinje och operationsdata. Begränsa flyttbara kandidater till Op10 enligt avsnitt 3.1.
3. Bestäm `NOW_Stockholm` en gång per körning. Klassificera varje rad som flyttbar eller fryst och spara frysningsorsak.
4. Normalisera `ProdGr`, konvertera datum korrekt och beräkna originalplanens status, tardiness och förseningspoäng med samma regler som ska användas efter omplanering.
5. Lägg in låsta och andra frysta operationer som fasta block på ursprunglig maskin/tid. Kontrollera överlapp och rapportera datakonflikter.
6. Beräkna maskinkapacitet enligt kalendern. Dela operationstider över arbetspass när det behövs; planera aldrig arbetstid utanför kalendern.
7. Skapa en EDD-baserad grundplan för flyttbara order. Beräkna Op10-start/slut, nedströms sluttid, status, tardiness, score och cap excess.
8. Utvärdera klustring och alternativmaskiner som kandidatändringar mot hela planen. Acceptera endast ändringar som följer hårda regler och målordningen. Återberäkna berörda maskiner och order efter varje accepterad ändring.
9. Om kandidaten bryter mot per-order-taket eller lämnar kvalificerat arbete oplanerat, lås berörda order till originalslot och schemalägg om resten enligt avsnitt 4.1. Återställ hela planen endast om brott eller oplanerat arbete kvarstår.
10. Kontrollera att varje kvalificerad order är planerad, att maskiner inte överlappar, att kalender och operationsordning följs och att ingen låst rad ändrats.
11. Tilldela `AI_OpkoPrioritet` efter faktisk starttid per ProdGr med stabil tie-breaker. Verifiera entydighet enligt formatkravet.
12. Skapa radkommentarer, KPI-sammanfattning och Excel-/CSV-resultat.

---

## 8. Kommentar per rad

`AI_Kommentar` ska vara på svenska och ange det som behövs för att förstå utfallet:

1. Identitet: `AO#<AoNr> (Order: <OrderNr>)`.
2. Planeringsbeslut och frysningsorsak, inklusive om raden ligger inom 4-timmarslåset.
3. Ursprunglig och ny ProdGr om maskin ändrats.
4. Föregångare och efterföljare på maskinen när dessa går att fastställa.
5. Klustring: sparad ställtid, artikel och referensorder.
6. Status före/efter, marginaldagar, faktisk försening före/efter och förseningspoäng efter.
7. Om raden låsts i lokal takreparation: ange att dess originalslot behölls och varför, samtidigt som andra order kunde omplaneras. Om hela kandidaten avvisats: ange kandidatens cap excess/oplanerade order och att hela originalplanen återställdes. Påstå inte att en cap-säker förbättring är omöjlig utan verifierad sökning.
8. Om kalenderdata saknas, täckningen är otillräcklig eller källdata innehåller en konflikt.

Exempel på låst rad:

```text
AO#88450 (Order: 206211): Fryst inom 4-timmarshorisonten. Ursprunglig Op10-start,
sluttid och maskin 10122 behålls; raden ligger kvar som fast kapacitetsblock.
Status Röd, marginal 0 dygn. Faktisk försening 0 dygn; förseningspoäng 0.
```

Exempel på lokal takreparation där andra order fortfarande kan ändras:

```text
AO#90202 (Order: 208376): Låst till originaltid 2026-10-12 08:00 och ProdGr
10122 i V5:s lokala takreparation. Kandidaten skulle öka faktisk försening med
0,5 kalenderdygn; originalslotten behålls. Övriga order på maskinen har
schemalagts om och kontrollerats på nytt.
```

Exempel på kandidat som avvisas på grund av kapöverskridande:

```text
AO#90202 (Order: 208376): V5-kandidaten på 10122 skulle öka faktisk försening
från 2,0 till 2,5 kalenderdagar (cap excess 0,5 dygn). Kandidaten avvisades.
Originaltid och originalmaskin behålls. Detta bevisar inte att en bättre
cap-säker plan är omöjlig.
```

---

## 9. Resultat och sammanfattning

### 9.1 Resultatflik

Fyll `tblAIAnglysisGetAoColorCodeList` enligt mallens kolumnordning. Behåll samtliga ursprungskolumner och värden. Kolumner med prefix `AI_` innehåller planförslaget. Minst följande data ska finnas per rad:

- Nycklar: `AoNr`, `AoPos`, `OpNr`, `ProdGr`, `ArtNr`.
- Originalvärden från baslinjen, inklusive start/slut, sluttid, `ColorCode`, `ColorName`, `OpkoPrioritet` och `OrdBerLevDat`.
- AI-värden: `AI_AoStartDatTid`, `AI_AoSlutDatTid`, `AI_TiSlutDat`, `AI_ColorCode`, `AI_ColorName`, `AI_OpkoPrioritet`, `AI_LogCreatDateTime`, `AI_Kommentar`, `AI_ProdGr`.
- Bevara mallens stavning och befintliga kolumnordning. Om `OrdBerLevDat` saknas i mallen, lägg till originalvärdet sist utan att ändra andra kolumners ordning.

Original `OpkoPrioritet` och AI-rang är olika skalor och ska inte jämföras som lika stora tal.

### 9.2 Sammanfattning

Visa före/efter på samma planeringspopulation och med samma datum-/statusregel:

- Totalt antal order, antal planerade och antal oplanerade med skäl.
- Antal och andel Gröna, Gula och Röda order.
- Jeeves `ColorName` separat från omräknad jämförbar baslinjestatus.
- Total tardiness, total progressiv förseningspoäng och största individuella tardiness.
- Motsvarande utfall för order som var sena i originalplanen.
- Antal order som blivit mer försenade, sammanlagd ökning och största ökning.
- Antal order och total cap excess. Ange tydligt om förseningsstaket uppnåddes.
- Antal order inom 4-timmarslås, redan påbörjade/fasta order och frysta av andra skäl. Kategorier ska vara ömsesidigt uteslutande eller tydligt förklarade.
- Antal omruttade order, klustringar, sparade ställtimmar och planändringar.
- Genomsnittlig och största tidighet som kompletterande mått, aldrig ensamt optimeringsmål.
- Inställningar som användes: låshorisont, statusgräns, trappsteg/poäng, tak, klusterfönster och `NOW_Stockholm`.

---

## 10. Leveransformat

- En Excel-fil med alla källflikar oförändrade samt resultat- och sammanfattningsflik.
- Resultatfliken följer mallens kolumnordning och har datumformat `yyyy-mm-dd hh:mm`.
- Radfärga efter `AI_ColorName`; formatera rubriker och frys rubrikraden.
- En semikolonavgränsad CSV av AI-resultattabellen för databasimport.
- Använd unika, tidsstämplade V5-namn: `<filnamn>_v5_resultat_<yyyyMMddHHmmss>.xlsx` och motsvarande `.csv`.
- Skriv inte över tidigare körningar.

---

## 11. Testscenarier och acceptanskriterier

Testa minst följande innan en implementation godkänns:

1. **Låshorisont:** originalstart före nu, exakt vid nu, exakt vid `nu + 4 h`, inom fönstret och efter fönstret. Endast kvalificerad Op10 efter fönstret får flyttas.
2. **Låst kapacitet:** låsta block reserveras på rätt maskin och tid; överlapp rapporteras och flyttas inte bort.
3. **Förseningstrappa:** testa 0, 1, 2, 3, 5, 6, 10 och mer än 10 dagar samt en deldag. Kontrollera den kumulativa formeln.
4. **Förseningsstak:** testa oförändrad och förbättrad tardiness, lokal låsning av ett försämrat jobb medan andra jobb fortfarande omplaneras, samt full återgång när lokal reparation inte räcker.
5. **Grön utan tardiness:** testa en order som tappar grön status men fortfarande blir klar senast på leveransdatumet. Status och faktisk tardiness ska rapporteras separat.
6. **En stor mot många små:** ge order olika `stycktid` men lika affärsvikt. Längre operationstid får påverka kapacitet, inte poängvikt.
7. **Röd order:** kontrollera att redan sena order inte ignoreras eller skjuts fram obegränsat.
8. **Tidig produktion:** kontrollera att framtida order inte flyttas onödigt långt fram när det inte förbättrar ett högre prioriterat mål.
9. **Klustring och alternativmaskin:** kontrollera kompatibilitet, kalendrar, ställtid och effekten på alla order på berörda maskiner.
10. **Omkörning:** små indataförändringar ska inte orsaka omotiverade förändringar utanför låshorisonten; rapportera planändringar.

En plan godkänns inte bara för att antalet Gröna ökar. Den måste också följa hårda begränsningar, redovisa takutfall, förseningspoäng och försämringar per order.

---

## 12. V5-motorn och begränsningar

V5-motorn implementerar 4-timmars låshorisont, progressiv förseningspoäng, prognos över återstående maskinkö vid sekvensering, alternativruttning som jämför planens målfunktion samt ett godkännandefilter för individuellt förseningsstak och oplanerade order. Om en order bryter mot taket eller blir oplanerad låses just den ordern till sin originalslot och resten av maskinkön schemaläggs om. Om brott eller oplanerat arbete kvarstår efter lokal reparation, avvisas kandidaten och hela originalplanen återställs. Kandidatens ursprungliga och kvarvarande fel redovisas separat.

Motorn använder heuristisk sökning, inte en fullständig optimeringslösare. Den kan därför avvisa en kandidat även om en annan cap-säker förbättring skulle kunna hittas; återfallet bevisar inte att en sådan plan är omöjlig. Originalplanens befintliga överlapp och datakonflikter måste också granskas separat. Påstå inte global optimalitet eller verifierad infeasibility utan en fullständig sökning.

---

## 13. Kända datafällor

| Fälla | Hantering |
|---|---|
| `ProdGr` som `10122` respektive `10122.0` | Normalisera före gruppering och jämförelse. |
| Excel-serienummer blandat med datetime | Konvertera uttryckligt och verifiera rimliga datum. |
| Saknad Op10-tid | Använd inte tyst en gissad varaktighet. Redovisa saknad tid och eventuell godkänd fallback separat. |
| Kalender saknas eller täcker inte schemat | Flagga; extrapolera inte utan uttryckligt godkännande. |
| Saknat `OrdBerLevDat` | Status och tardiness kan inte beräknas; frys raden och behåll originalstatus. |
| Null eller okänd `ColorName` | Bevara originalvärdet. Om leveransdatum finns, härled AI-status från marginalen; låt inte okänd originalfärg automatiskt betyda Grön. |
| Null `OrderNr` | Bevara AoNr som identifierare och rapportera att OrderNr saknas. |
| Skillnad mellan statusröd och faktisk sen | En order kan vara Röd med noll tardiness enligt marginalregeln; redovisa båda måtten. |
| Frysta block överlappar | Rapportera inkonsekvens; ändra inte frysta tider för att dölja konflikten. |
| Kandidat bryter mot taket eller lämnar arbete oplanerat | Avvisa kandidaten, återställ originalplanen och redovisa kandidatens takbrott/oplanerade order. Påstå inte att en cap-säker förbättring är omöjlig utan fullständig sökning. |
| Stor `stycktid` misstolkas som ordervärde | Använd `stycktid` endast som tidsåtgång. Alla order har lika affärsvikt tills ett separat, validerat värdefält införs. |

---

## 14. Grundprincip

Skapa en plan som en erfaren produktionsplanerare kan genomföra och förstå:

- Försök få så många order som möjligt Gröna, men aldrig genom att bryta fysiska regler eller dölja försämring.
- En order som redan är sen ska fortfarande ha ett värde; varje ytterligare försening kostar progressivt mer.
- Ingen order får som standard bli mer försenad än i originalplanen. Om detta inte går ska avvikelsen visas tydligt.
- Alla order har samma affärsvikt. Maskintid är kapacitetsförbrukning, inte kundvärde.
- Respektera fyra timmars låsning, verklig maskinkapacitet och godkända maskinrutter.
- Redovisa varför planen är bättre och vilka enskilda order som påverkas.