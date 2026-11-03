# SkärAI – lösningsunderlag för identifiering av vändskär

> **Kund:** AGES  
> **Syfte:** Beskriva möjliga arbetssätt, vad som krävs för en fungerande lösning och hur en avgränsad pilot kan genomföras. Dokumentet är ett verksamhets- och beslutsunderlag, inte en teknisk instruktion.

## 1. Sammanfattning

AGES vill kunna fotografera ett vändskär och snabbt hitta rätt beteckning och produktinformation. En bild kan ofta hjälpa till att hitta rätt form eller produktfamilj, men den kan inte alltid visa exakt storlek, tjocklek, hörnradie, spånbrytare eller sort. Två skär kan se nästan identiska ut och ändå skilja sig med omkring en millimeter eller mindre.

Därför bör lösningen inte lova automatisk identifiering från ett enda foto. En bättre första lösning är ett sökbart, kvalitetssäkrat bibliotek med AGES vanligaste skär, riktiga verkstadsbilder och leverantörsinformation. Bildsökning kan föreslå några kandidater. Användaren jämför dem med mått, märkning eller förpackning och bekräftar resultatet. Om underlaget inte räcker ska lösningen be om mer information eller lämna ärendet för granskning.

**Rekommendation:** Börja med en avgränsad pilot för de vanligaste skären. Kombinera standardiserad fotografering, ett verifierat produktbibliotek, bildbaserad kandidatsökning och mänsklig bekräftelse. Utvärdera först när AGES har ett representativt testmaterial. Överväg mer avancerad automatisering först när mätningar visar att den tillför nytta.

## 2. Behov och avgränsning

Målet är att minska tiden som går åt till att identifiera skär och söka i kataloger. Lösningen ska hjälpa användaren att hitta en korrekt produkt, inte gissa när bild eller produktinformation är otillräcklig.

En identifiering kan behöva innehålla flera nivåer:

- **Form och familj:** ofta möjliga att bedöma från en tydlig bild.
- **Exakt dimension:** exempelvis skärlängd, tjocklek och hörnradie. Kräver ofta skala, mätning, märkning eller förpackning.
- **Utförande:** hål, spånbrytare och om skäret kan användas på en eller båda sidor. Kan kräva flera bildvinklar.
- **Leverantörsvariant:** tillverkarens produktbeteckning, sort och beläggning. Behöver normalt jämföras med leverantörens produktinformation.

En korrekt familj är inte alltid en korrekt artikel. Gränssnittet bör visa skillnaden tydligt och inte presentera ett familjeförslag som en säker identifiering av exakt produkt.

**Utanför en första pilot:** automatisk beställning, maskinstyrning och ett löfte om att varje produkt kan identifieras från ett enda foto. Sådana behov kan utvärderas senare.

## 3. Lösningsalternativ

| Alternativ | Hur det fungerar | Fördelar | Begränsningar |
|---|---|---|---|
| Sökbar produktkatalog | Användaren filtrerar på form, mått, märkning och leverantör. | Förutsägbart, lätt att granska och en bra grund för all vidare utveckling. | Kräver manuell inmatning och användaren behöver känna till några kännetecken. |
| Bildsökning med bekräftelse | Ett foto jämförs med verifierade referensbilder och visar några möjliga produkter. Användaren bekräftar eller avstår. | Snabbare första urval och möjlighet att återanvända AGES egna bilder. Lämpligt för en pilot. | Liknande skär kan rangordnas fel. Bildlikhet bevisar inte exakt dimension eller produktidentitet. |
| Bild, märkning och produktdata tillsammans | Bilden kombineras med avläsning av gravyr, mått, förpackning och leverantörsinformation. | Kan lösa fler fall och minska manuellt katalogsökande. | Kräver tydliga bilder och tillförlitliga produktuppgifter. Svårtolkad märkning måste kunna lämnas obesvarad. |
| Specialtränad bildmodell | En modell tränas eller anpassas med många märkta exempel från AGES. | Kan bli bättre för en stabil och väl avgränsad produktmängd. | Kräver många representativa exempel, löpande kvalitetssäkring och mer investering. Bör inte vara första steget. |

### Rekommenderad väg

Använd en stegvis hybridlösning:

1. Skapa en verifierad katalog över ett begränsat urval av vanliga skär.
2. Samla in standardiserade bilder från AGES faktiska arbetsmiljö.
3. Använd bildsökning för att hitta och rangordna kandidater, inte för att fastställa identitet på egen hand.
4. Be användaren komplettera med sidobild, mått, märkning eller förpackningsuppgift när kandidaterna är svåra att skilja åt.
5. Spara användarens bekräftelser och korrigeringar så att biblioteket kan förbättras kontrollerat.
6. Mät resultatet innan ni tar ställning till mer automatisering eller en specialtränad modell.

### Förslag på lösning: Lovable, Azure AI Foundry och RAG

I pilotförslaget används Lovable för användarens arbetsflöde och Azure AI Foundry för de AI-modeller som analyserar bilder och jämför kandidater. RAG används för att hämta relevant, verifierad produktinformation ur AGES bibliotek innan den generativa AI:n svarar. RAG betyder här att AI:n får ett avgränsat faktaunderlag vid varje fråga; det innebär inte att modellen tränas om.

**Föreslagen ansvarsfördelning:**

- **Lovable:** användaren tar eller laddar upp bilder, får instruktioner om kompletterande vyer, jämför förslag och bekräftar eller avvisar identifieringen.
- **AGES produktbibliotek:** lagrar verifierade produktuppgifter, referensbilder, leverantörsuppgifter och information om källan och granskningen. Originalbilder hålls åtskilda från sökindexet.
- **Azure AI Foundry:** tillhandahåller de valda modellerna för bildanalys, bildembedding och generativ jämförelse. Den valda embeddingmodellen måste uttryckligen stödja bildindata. Modell-, regions- och API-stöd verifieras innan pilotens teknikval låses.
- **Sökindex och RAG:** en vektorsökning hittar visuellt närliggande, godkända referenser. Exempelvis kan Azure AI Search användas för vektorer och sökbar produktmetadata, medan originalbilderna lagras separat med kontrollerad åtkomst. RAG hämtar sedan produktfakta och källor för de hittade kandidaterna.
- **Webbsökning:** används bara som reserv när den interna sökningen inte ger tillräckligt många användbara kandidater. Den ska söka i tillåtna och spårbara källor, i första hand tillverkarnas och AGES leverantörers officiella kataloger.
- **Säker mellanhand:** en skyddad backend tar emot anrop från Lovable, sköter intern sökning och eventuell webbsökning och anropar Foundry. Hemligheter och modellnycklar ska inte finnas i webbläsaren.

#### Verktyg och tjänster att gå igenom med IT

Tabellen är ett förslag för en pilot, inte ett beslut om att alla tjänster redan är godkända. RAG är ett arbetssätt: sökindexet hämtar relevanta, godkända fakta som den generativa AI:n får använda.

| Verktyg eller tjänst | Vad det gör i lösningen | Vad IT behöver bedöma eller tillhandahålla |
|---|---|---|
| **Lovable** | Användargränssnitt för att fotografera/ladda upp, visa 3–5 kandidater och registrera validering. | Godkännande av tjänsten som SaaS, inloggning/SSO, datahantering, källkod och publicering. Lovable ska inte lagra modellnycklar eller vara enda långtidslagring för produktbilder. Om tjänsten inte godkänns behöver gränssnittet byggas på en plattform som AGES redan godkänt. |
| **Azure AI Foundry** | Anropar en generativ modell för att analysera och rangordna kandidater samt en modell med bildstöd för bildembedding. Dessa kan vara separata modeller. | Azure-prenumeration/projekt, godkänd region, modellåtkomst, kvoter, kostnadsgränser och kontroll av att vald modell faktiskt tar bilder som indata för embedding. Modellnamn och stöd måste verifieras innan val. |
| **Azure AI Search** | Vektor- och metadataindex för bildlikhet, leverantörsfilter och RAG-hämtning. Kan även kombinera vektor- och textsökning. | Sökresurs och lämplig kapacitet, indexutformning, åtkomstkontroll och nätverkslösning. Indexera bara godkända referenser som interna, verifierade träffar. |
| **Azure Blob Storage** | Privat lagring av originalbilder, referensbilder och eventuella etikett-/förpackningsbilder. | Privat lagringskonto, kryptering, behörigheter, livscykel/retention, backup och eventuell privat nätverksåtkomst. |
| **Azure Functions** | Skyddad backend som tar emot anrop från Lovable, skapar embedding, söker internt, gör webbsökning vid behov och anropar Foundry. | Godkänd körmiljö, API-skydd, nätverksåtkomst till Azure-tjänster och godkänd utgående trafik till eventuell webbsöktjänst. En annan befintlig backendplattform kan användas om den uppfyller kraven. |
| **Microsoft Entra ID** | Inloggning och roller för användare, validerare och bibliotekets granskare. | Appregistrering, SSO och åtkomstgrupper. Skilj på att välja en kandidat och att godkänna nya referenser. |
| **Managed Identity och Azure Key Vault** | Backendens identitet och säker hantering av eventuella hemligheter. | Hanterad identitet där tjänsterna stöder det; annars hemligheter i Key Vault. Ge minsta möjliga behörighet och inga nycklar i webbläsaren. |
| **Godkänd webbsöktjänst** | Reservsökning efter officiella produktkällor när AGES bibliotek inte räcker. | Beslut om tillåten söktjänst, licens och villkor, tillåtna domäner, loggning samt om frågebilder eller produktdata får skickas externt. Exempel på teknisk väg kan vara Foundry-grounding med Bing om det är tillgängligt och godkänt för AGES; annars används en annan IT-godkänd söktjänst. |
| **Azure Monitor / Application Insights** | Mäter svarstid, fel, kostnad och hur ofta intern sökning respektive webbreserv används. | Loggningspolicy, åtkomst och retention. Undvik att logga råbilder eller känsligt innehåll om det inte uttryckligen godkänts. |
| **GitHub eller Azure DevOps** | Versionshantering och kontrollerad publicering mellan utvecklings-, test- och produktionsmiljö. | Använd AGES befintliga källkods- och releaseprocess, miljöseparering och godkännandegrindar. |

**Kort beställnings- och beslutslista till IT:**

1. Bekräfta om Lovable får användas med AGES inloggning och bilder. Fastställ godkänd reservplattform om svaret är nej.
2. Bekräfta Azure-prenumeration, region, miljöer och kostnadsägare för Foundry, AI Search, Blob Storage, Functions, Key Vault och Monitor.
3. Godkänn exakta AI-modeller först efter kontroll av bildembedding, region, datahantering, licens, kvot och pris.
4. Besluta om webbsökning får gå ut på internet, vilken söktjänst och vilka tillverkare/leverantörer som ska prioriteras.
5. Bestäm SSO, användarroller, nätverksåtkomst, retention för bilder och loggar samt vem som får godkänna att validerade bilder blir nya sökreferenser.

Vid varje uppladdning är målet att visa 3–5 källbelagda förslag med leverantör och beteckning. Interna godkända träffar visas först; webbsökningen kompletterar endast vid behov. Om färre än tre kandidater kan styrkas visar lösningen färre och ber om komplettering i stället för att fylla ut listan med gissningar.

**Flöde för att bygga biblioteket:**

1. AGES lägger in referensbilder och kontrollerade produktuppgifter.
2. En ansvarig verifierar att bilderna verkligen hör till produkten och godkänner dem för användning.
3. Godkända bilder bearbetas konsekvent och omvandlas till bildembeddings med den valda modellen.
4. Embeddings och sökbar produktmetadata indexeras. Originalbild, leverantörskälla, källadress och granskningsstatus bevaras.
5. Nya eller osäkra poster blir inte sökbara som verifierade referenser förrän de har granskats.

**Flöde vid identifiering:**

1. Användaren fotograferar skäret i Lovable och anger eventuell känd information, till exempel leverantör eller mått.
2. Den skyddade backendfunktionen kontrollerar bildkvalitet och begär vid behov en ny bild eller en kompletterande vy.
3. En bildembedding används först för att söka i AGES godkända bild- och produktbibliotek. RAG hämtar fakta och källor till de närmaste kandidaterna.
4. Om den interna sökningen inte ger ett tillräckligt urval gör backend en separat webbsökning. Sök i första hand officiella tillverkar- och leverantörskällor. Spara källa och produktlänk för varje extern träff.
5. Den generativa AI:n jämför bild och produktuppgifter och rangordnar 3–5 källbelagda kandidater med leverantör och beteckning. Kandidater från AGES bibliotek skiljs tydligt från externa, ännu inte verifierade träffar.
6. Lovable visar kandidaterna med källa, relevanta skillnader och tydlig valideringsstatus. Användaren väljer rätt beteckning, korrigerar uppgiften eller anger att inget förslag passar.
7. En validerad beteckning kopplas till den uppladdade bilden och produktposten. Bildembedding och RAG-index uppdateras så att den granskade bilden kan förbättra framtida sökningar. Ändringen loggas med användare, tidpunkt och källa.
8. Om valideraren saknar behörighet, eller om extern produktinformation behöver kontrolleras, sparas uppdateringen som väntande granskning. Den används inte som godkänd referens förrän granskningen är klar.

Vid små skillnader i mått ska bildsökningen bara minska antalet kandidater. Exakt dimension verifieras med produktuppgift, märkning, förpackning eller fysisk mätning. Generativ AI och RAG gör inte ett vanligt foto till ett tillförlitligt precisionsmått.

Målet är att ge användaren 3–5 relevanta förslag vid varje uppladdning. Förslagen ska hämtas från AGES bibliotek och vid behov kompletteras med spårbara externa källor. Om färre än tre beteckningar kan styrkas får AI:n inte fylla ut listan med påhittade produkter; den ska visa vad som faktiskt hittats och begära mer information eller granskning.

#### Instruktion till den generativa AI:n

Analysera den uppladdade bilden. Börja med att beskriva endast synliga egenskaper, till exempel form, hål, spånbrytare, gravyr och bildkvalitet. Använd först kandidater och produktuppgifter som hämtats från AGES godkända bibliotek. Om dessa inte räcker ska du använda den anslutna webbsökningen, inte hitta på information eller låtsas att du har sökt på webben. Prioritera tillverkarens och AGES leverantörers officiella kataloger. För varje extern kandidat ska du ange leverantör, produktbeteckning, källa och länk, och markera att den inte är verifierad av AGES. Rangordna 3–5 kandidater från det insamlade underlaget och förklara kort vad som stöder eller talar emot varje kandidat. Skilj mellan interna, verifierade uppgifter och externa, obekräftade uppgifter. Hitta aldrig på en beteckning, leverantör, källa eller mått. Dra inte slutsatser om exakta mått, hörnradie, sort eller leverantörsvariant om bild och källunderlag inte styrker dem. Om färre än tre kandidater kan styrkas ska du redovisa färre och be om kompletterande vy, märkning, förpackning, mätning eller manuell granskning. Presentera aldrig en osäker kandidat som en säker identifiering. Användarens val validerar kandidatens koppling till bilden, men nya eller externa produktuppgifter behöver godkännas enligt AGES granskningsrutin innan de blir del av det godkända biblioteket.

En fristående flödesskiss finns i [SkärAI-flödesskiss.html](SkärAI-flödesskiss.html).

## 4. Nästan identiska skär och små måttskillnader

När skär skiljer sig med omkring en millimeter, eller när skillnaden gäller hörnradie eller tjocklek, är ett vanligt foto inte ett tillförlitligt mätinstrument. Perspektiv, kameravstånd, fokus, ljus och slitage påverkar hur måtten ser ut. En referensskala hjälper, men gör inte automatiskt en sned eller perspektivförvrängd bild mätbar.

Lösningen bör därför skilja mellan **visuell likhet** och **verifierad produktidentitet**:

- Bilden används för att hitta rätt form och en hanterbar kandidatlista.
- Exakta mått hämtas från märkning, förpackning, leverantörsuppgifter eller mätning.
- När flera kandidater fortfarande är möjliga visas skillnaderna sida vid sida, till exempel tjocklek, hörnradie, spånbrytare och leverantör.
- Användaren kan välja att mäta med skjutmått eller ange en känd uppgift från förpackningen.
- Om skillnaden inte kan avgöras ska lösningen visa att identifieringen är osäker och be om komplettering. Den ska inte välja en kandidat bara för att den ligger först i sökresultatet.

Ett användbart resultat kan alltså vara: rätt familj hittad, men exakt variant behöver verifieras. Det är bättre än ett precist men felaktigt svar.

## 5. Förslag på fotografering

Fotograferingen bör vara enkel nog att följa i vardagen och tillräckligt konsekvent för att bilder ska gå att jämföra.

### Standardbilder per skär

- **Ovanifrån:** hela skäret synligt, kameran så vinkelrät mot ovansidan som möjligt.
- **Från sidan:** visar tjocklek, släppningsvinkel och eventuell beläggning eller profil.
- **Undersida:** när skäret har olika utförande på över- och undersida eller skillnaderna påverkar identifieringen.
- **Närbild på märkning:** gravyr och andra synliga kännetecken i fokus.
- **Förpackning eller etikett:** om den finns tillgänglig och hör till just det fotograferade skäret.

För ett snabbt arbetsflöde kan användaren börja med en ovanbild. Systemet ber bara om de kompletterande vyer som behövs för att skilja kvarvarande kandidater åt.

### Fotomiljö och bildkvalitet

- Lägg ett skär i taget på en ren, matt, enfärgad bakgrund med tydlig kontrast mot skäret.
- Använd jämnt, diffust ljus från mer än en riktning. Undvik direkt blixt och hårda reflexer från metall eller beläggning.
- Håll kameran stilla och nära nog för att detaljer och eventuell gravyr ska vara skarpa. Använd makroläge om telefonen har ett sådant.
- Fyll en stor del av bilden med skäret, men lämna lite utrymme runt kanterna. Undvik att skymma det med fingrar eller verktyg.
- Ta bilden rakt framifrån för måttjämförelser. Sneda bilder kan fortfarande vara användbara för form, men inte som grund för precisa dimensioner.
- Lägg en skala eller ett känt mått i samma plan som skäret när storlek behöver uppskattas. För kritiska skillnader är skjutmått eller dokumenterade produktmått säkrare än bildmätning.
- Ta om bilden om den är suddig, överexponerad, skymd eller visar flera skär som inte går att separera.

### Märkning av referensmaterial

Varje referens bör kopplas till rätt produkt och, när det är möjligt, till det fysiska skär som fotograferades. Spara även uppgift om vy, datum, källa och om produktidentiteten är kontrollerad. Flera bilder av samma fysiska skär ska inte räknas som flera oberoende exempel när lösningen utvärderas.

## 6. Vad AGES kan göra för att lösningen ska fungera bättre

Kvaliteten på produktunderlaget och arbetsflödet kommer att påverka resultatet minst lika mycket som valet av bildmodell. AGES kan bidra genom att:

- välja ut de vanligaste skären och beskriva vilka användningsfall som ger störst nytta;
- samla in flera fysiska exemplar av varje prioriterad produkt, inte bara flera foton av samma exemplar;
- låta kunniga medarbetare verifiera produktbeteckning, dimensioner, variant och leverantör innan materialet används som referens;
- fotografera både nya och använda skär, och markera slitage, skador, beläggning och smuts där det är relevant;
- spara förpackning, etikett, inköpsuppgift eller leverantörsdatablad tillsammans med produktinformationen;
- ange vad som ska hända när ingen kandidat passar, när produktuppgifter saknas eller när två alternativ inte kan skiljas åt;
- utse ansvariga som får godkänna nya referenser och rätta felaktiga etiketter;
- bestämma om bilder får hanteras i molntjänster och vilka krav som gäller för lagring och åtkomst;
- ge återkoppling på om verktyget faktiskt sparar tid och om resultatet är tillräckligt tydligt för operatörerna.

Börja hellre med ett litet, välkontrollerat bibliotek än ett stort bibliotek med osäkra etiketter. Felmärkta referensbilder kan göra framtida förslag sämre.

## 7. Leverantörer och andra skär

Leverantörerna bör ingå i lösningen, men som en kontrollerad källa till produktinformation och inte som en ersättning för AGES egna referensbilder.

### Rekommenderat användningssätt

- Börja med leverantörer som står för en stor del av AGES inköp eller identifieringsbehov.
- Samla leverantörens produktbeteckning, standardiserad beteckning, dimensioner, hörnradie, spånbrytare, sort och relevanta ersättnings- eller korsreferenser.
- Håll isär standardiserad produktfamilj och leverantörens egna varianter. Två produkter med liknande standardbeteckning kan skilja sig i spånbrytare, sort eller avsett användningsområde.
- Använd leverantörsbilder och datablad som kompletterande referens. Märk tydligt att en katalogbild inte är samma sak som ett foto av skäret i AGES miljö.
- Kontrollera med leverantören vilka produktbilder och kataloguppgifter AGES får lagra och använda.
- Be leverantören hjälpa till att reda ut tvetydiga artikelnummer, utgångna produkter och rekommenderade ersättare.

Andra skär som AGES använder bör hanteras med samma principer. Om ett skär inte finns i biblioteket ska användaren kunna markera att inget förslag stämmer. Produkten kan då läggas till efter granskning, tillsammans med verifierade uppgifter och nya bilder. Systemet ska inte tvinga in ett okänt skär i den närmaste befintliga kategorin.

En rimlig start är att prioritera skär som förekommer ofta och där AGES har tillgång till både fysiska exemplar och tillförlitlig produktinformation. Därefter kan biblioteket utökas med fler leverantörer, produktfamiljer och ovanliga varianter.

## 8. Pilot och utvärdering

Piloten bör omfatta ett urval av vanliga produkter samt svåra exempel där skären liknar varandra. Ta med olika fysiska exemplar, leverantörer, slitagegrad och fotoförhållanden.

Utvärdera minst:

- hur ofta rätt produktfamilj finns bland de första förslagen;
- hur ofta exakt produkt blir korrekt efter användarens kontroll;
- hur ofta systemet avstår när underlaget inte räcker;
- hur ofta ett felaktigt förslag presenteras som säkert;
- hur ofta användaren behöver ta en ny bild eller ange mått;
- hur lång tid identifieringen tar jämfört med dagens arbetssätt;
- vilka produkter och bildförhållanden som orsakar flest fel.

Testa på fysiska skär som inte redan har förekommit som referensbilder. Annars riskerar utvärderingen att visa att systemet känner igen samma fotograferade exemplar i stället för att det klarar en ny produkt av samma typ. Behåll ett separat testmaterial oförändrat medan lösningen förbättras.

AGES och projektgruppen behöver gemensamt bestämma vilken träffsäkerhet och tidsbesparing som motiverar fortsatt investering. Särskilt viktigt är att sätta en låg tolerans för självsäkra fel och acceptera att lösningen ibland ber om mer information.

## 9. Föreslagna nästa steg

1. AGES väljer ett första urval av vanliga skär och beskriver dagens identifieringsflöde.
2. AGES samlar fysiska exemplar, korrekta produktuppgifter och foton enligt fotograferingsförslaget.
3. Projektgruppen går igenom materialet och identifierar vilka skillnader som kräver mätning, märkning eller leverantörsdata.
4. Tillsammans bestämmer ni pilotens användarflöde, integritetskrav och hantering av osäkra eller okända produkter.
5. Genomför piloten och jämför den med dagens arbetssätt med samma testmaterial.
6. Besluta därefter om biblioteket ska utökas, om fler leverantörskällor behövs eller om mer avancerad AI är motiverad.

## 10. Detaljerad implementeringsplan

Planen är avsedd att genomföras i etapper. Varje etapp avslutas med ett beslut eller ett verifierbart resultat innan nästa börjar.

### Fas 1: Besluta omfattning och spelregler

- AGES väljer de vanligaste produktfamiljerna och de leverantörer som ska ingå i piloten.
- Kartlägg hur skär identifieras i dag, vilka uppgifter som finns tillgängliga vid fotografering och var felidentifiering får störst konsekvens.
- Bestäm vilka användare som får bekräfta en kandidat och vilka som får godkänna nya produkter eller externa källor.
- Bestäm krav för bildlagring, åtkomst, personuppgifter, molnregion och användning av externa söktjänster.
- Definiera vad ett användbart svar innebär: mål om 3–5 förslag, krav på leverantör och källhänvisning samt hur systemet ska agera när underlaget är otillräckligt.

**Leverans och beslut:** godkänd pilotavgränsning, prioriterad leverantörslista, användarroller och regler för när data får bli godkänd referens.

### Fas 2: Bygga och kvalitetssäkra produktbiblioteket

- Samla produktbeteckningar, leverantörernas artikelnummer, dimensioner, spånbrytare, sort, produktlänkar och ersättningsreferenser.
- Håll isär standardiserad produktidentitet och leverantörens egna varianter; en leverantörsartikel ska inte automatiskt betraktas som utbytbar mot en annan.
- Fotografera fysiska exemplar enligt fotoinstruktionen och koppla varje bild till verifierad produkt, leverantör, vy och källa.
- Samla även svåra närliggande kandidater och bilder av nya respektive slitna skär.
- Utse dataägare och skapa ett enkelt granskningsflöde för nya och ändrade uppgifter.

**Leverans och beslut:** pilotbibliotek med verifierade poster, bildmaterial, källor och en separat lista över olösta eller tvetydiga produkter.

### Fas 3: Välja och konfigurera Azure-komponenter

- Konfigurera Lovable för autentiserat uppladdnings- och valideringsflöde.
- Välj en skyddad backend för att hantera anrop mellan Lovable, sökningen och Azure AI Foundry. Förvara hemligheter endast på serversidan.
- Välj lagring för originalbilder och ett sökindex som stöder bildvektorer samt filtrering på leverantör, produktfamilj och godkännandestatus.
- Välj Azure AI Foundry-modeller först efter att stöd för bildindata, embedding, region, åtkomst och kostnad har verifierats.
- Versionsmärk modell och bildbearbetning så att referensbilder och uppladdade bilder jämförs på samma sätt.
- Konfigurera loggning, åtkomstkontroll, hantering av fel och kostnadsuppföljning.

**Leverans och beslut:** fungerande miljö med separerad klient, backend, bildlagring, sökindex och verifierade modellval.

### Fas 4: Indexera bilder och produktinformation

- Kontrollera och normalisera produktmetadata innan indexering.
- Bearbeta godkända referensbilder konsekvent och skapa bildembedding med vald modell.
- Indexera vektorer tillsammans med produktidentitet, leverantör, källhänvisning, vy och granskningsstatus.
- Gör endast godkända referenser sökbara som interna träffar.
- Testa att metadatafilter och bildsökning ger relevanta kandidater och att modellen och indexet har kompatibla versioner.

**Leverans och beslut:** sökbart, versionsmärkt bibliotek och dokumenterade resultat från grundtester.

### Fas 5: Implementera sökning och webbreserv

- Vid varje uppladdning skapas en sökfråga från bilden och eventuell information som användaren anger.
- Sök först i AGES vektor- och RAG-bibliotek och hämta produktuppgifter samt källor för de bästa interna kandidaterna.
- Om intern sökning inte ger tillräckligt många relevanta träffar, anropa en godkänd webbsökning från backend.
- Prioritera officiella tillverkar- och leverantörssidor. Spara URL, sidtitel, hämtningstid och eventuell produktidentifierare; använd inte obestyrkta sökresultat som verifierade produktfakta.
- Slå ihop och deduplicera interna och externa kandidater utan att blanda ihop olika leverantörsvarianter.
- Rangordna upp till fem förslag. Om färre än tre är källbelagda ska tjänsten visa det tydligt och inte hitta på återstående kandidater.

**Leverans och beslut:** en backendtjänst som visar intern träff först, använder extern sökning endast vid behov och kan förklara var varje förslag kommer ifrån.

### Fas 6: Bygga generativ jämförelse och användarflöde

- Skicka bilden och det begränsade kandidatunderlaget till den generativa modellen.
- Använd AI-instruktionen i det här dokumentet och kräv strukturerade kandidater med leverantör, beteckning, källa, status och kort motivering.
- Visa tydliga skillnader mellan interna verifierade träffar och externa obekräftade träffar.
- Visa 3–5 kandidater när så många kan styrkas, men låt användaren välja komplettera, inget av dessa eller manuell granskning.
- Be om sidobild, gravyr, förpackning eller fysisk mätning när exakta mått inte går att verifiera visuellt.
- Spara användarens val, korrigering och eventuell kommentar så att resultat kan följas upp.

**Leverans och beslut:** end-to-end arbetsflöde i Lovable med tydliga källor, validering och säkert avstående.

### Fas 7: Validering och kontrollerad biblioteksförbättring

- När en behörig användare bekräftar en kandidat kopplas bilden till den valda produktposten och valideringshändelsen loggas.
- Uppdatera produktmetadata och RAG-sökbar information efter validering.
- Skapa embedding för den uppladdade bilden och lägg den till som ny referens först när bildkvalitet, produktkoppling och valideringsbehörighet är godkända.
- Lägg externa webbfynd i en väntande granskningskö. Extern text eller en genererad beteckning blir inte automatiskt en godkänd AGES-produktpost.
- Ge möjlighet att ångra eller korrigera felaktiga kopplingar och ta bort dem ur det aktiva indexet.
- Separera indexuppdatering från modellträning: ny bild och verifierad metadata förbättrar hämtningen, men innebär inte att grundmodellen har tränats om.

**Leverans och beslut:** spårbar återkopplingsloop med granskningsstatus, historik och möjlighet att rätta felaktiga referenser.

### Fas 8: Pilot, mätning och lanseringsbeslut

- Skapa ett fryst testmaterial med olika fysiska exemplar, leverantörer, slitagenivåer och svåra närliggande produkter.
- Testa intern sökning separat från webbreserv så att det framgår var förslagen kommer ifrån och vilken väg som fungerar.
- Mät om rätt produkt finns bland de första förslagen, korrekt val efter användargranskning, felaktigt självsäkra svar, andel avstående, webbkällornas kvalitet, svarstid och kostnad.
- Jämför identifieringstid med dagens arbetssätt och granska fel tillsammans med AGES sakkunniga.
- Besluta om pilotens resultat motiverar bredare produktbibliotek, fler leverantörer eller vidare automatisering.

**Leverans och beslut:** pilotrapport med mätetal, kända begränsningar, kostnadsbild och rekommendation om nästa fas.

## 11. Frågor att besvara tillsammans

- Vilka skär orsakar mest söktid eller störst risk för fel i dag?
- Finns märkning, förpackning eller skjutmått normalt tillgängligt när identifieringen görs?
- Vilka leverantörer och produktfamiljer ska prioriteras i piloten?
- Vilka produktuppgifter får hämtas eller lagras från leverantörer?
- Får bilder hanteras i en extern molntjänst, och vilka lagrings- och åtkomstkrav gäller?
- Vem på AGES får verifiera och godkänna produktuppgifter och referensbilder?
- Är det acceptabelt att verktyget först identifierar familjen och därefter ber användaren verifiera exakt dimension eller variant?
- Vilken tidsbesparing och vilken nivå av korrekta identifieringar krävs för att lösningen ska vara värd att införa?
- Vilken godkänd söktjänst får användas för extern webbsökning, och vilka leverantörs- eller tillverkarsidor ska prioriteras?
- Ska validering av en användare direkt lägga till en ny bild i det aktiva vektorindexet, eller krävs alltid separat granskning?
