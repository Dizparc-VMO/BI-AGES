# AI Omplanering V6

V6 finns parallellt med V5. Befintliga versioner och SQL-tjänsten ändras inte.
Planeringslogiken från V5 behålls; låshorisonten är nu en inställning per körning.

## Skrivbordsapp

Starta från projektroten med `python omplanering_app_v6.py`.
Beroendena är oförändrade och finns i [requirements.txt](requirements.txt).

1. Välj arbetsbok och utkatalog.
2. Ange **Låshorisont** i timmar. **4 timmar är standard**.
3. Tryck **Kör omplanering**.

Decimaler kan anges med punkt eller komma, exempelvis `2,5`.
`0` tar bort framtida låshorisont, men redan påbörjade operationer och andra
frysta rader förblir frysta. Negativa värden, tomt fält och NaN/oändlighet avvisas.

Inställningen sparas separat för V6 mellan starter. Saknad eller ogiltig sparad
låshorisont ger standardvärdet 4. Klusterfönstret sparas också.
Körningen använder de värden som valdes när Kör trycktes.

Använd låshorisont visas i körloggen, sammanfattningen i appen och Excel samt
`stats['lock_horizon_hours']`. Excel- och CSV-resultat får tidsstämplade namn
som innehåller `_v6_resultat_`.

## Kommandorad och Python

Motorn kan också köras med `python omplanering_core_v6.py <arbetsbok> --lock-horizon-hours 6`.
Utan flaggan används 4 timmar. I Python tar `run_replanning()` och
`compute_plan()` argumentet `lock_horizon_hours=4`.

## Tester

Kör `python -m unittest test_omplanering_v5 test_omplanering_v6 -v` från projektroten.
Testerna omfattar V5-regressioner, ändrad låshorisont, gränsvärden, noll,
decimaler, validering, isolerade körningar, exporter och gränssnittets överföring
av inställningen. UI-testerna körs utan att öppna ett fönster.

## Regler och begränsningar

Öppna [dokumentation_v6.html](dokumentation_v6.html) i webbläsaren eller via
appens knapp **Dokumentation V6** för flödesschema, användarguide, exempel,
parametrar och KPI-förklaringar. Sidan fungerar offline och kan skrivas ut.

Se [instuktion_v6.md](instuktion_v6.md) för ändringen relativt V5.
Förseningsstak, progressiv förseningspoäng, lokal takreparation, kalenderregler
och alternativruttning är oförändrade. Motorn är heuristisk och garanterar inte
global optimalitet. Granska varningar och originalplanens överlapp före användning.

Den befintliga SQL-tjänsten fortsätter använda sin tidigare version; denna
leverans gäller V6-skrivbordsappen och V6-motorns Excel-/Python-/CLI-väg.