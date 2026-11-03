# AI Omplanering — Instruktion V6

**Version:** 6.0 | **Datum:** 2026-10-08

V6 bygger på [instuktion_v5.md](instuktion_v5.md). Alla planeringsregler,
målordning, datakrav och begränsningar i V5 gäller med följande uttryckliga
ersättningar. Detta är en parameterändring, inte en ny optimeringslogik.

## Konfigurerbar låshorisont

- `LOCK_HORIZON_HOURS = 4` är standardvärdet.
- Användaren kan ändra **Låshorisont** i gränssnittet före varje körning.
- Körningen använder det valda värdet som `lock_horizon_hours`, utan att ändra
  globala värden eller påverka andra körningar.
- Tillåt ändliga, icke-negativa timmar som ryms inom datumintervallet.
  Decimalpunkt och decimalkomma accepteras.
- Spara senast valda värdet separat för V6. Vid första start, saknad inställning
  eller ogiltigt sparat värde används 4 timmar.

Alla hänvisningar i V5 till ”4 timmar”, ”4-timmarslås” och
`NOW_Stockholm + 4 timmar` avser i V6 det **valda värdet**, med 4 som standard.

### Frysningsgräns

En annars kvalificerad Op10 får endast flyttas om dess ursprungliga start är
**senare än `NOW_Stockholm + lock_horizon_hours` timmar**.

Start exakt på gränsen är fryst. Frysta operationer behåller originalstart,
originalslut och originalmaskin och reserverar kapacitet som tidigare.

| Scenario | Utfall för annars kvalificerad Op10 |
|---|---|
| Standard 4 h, start om exakt 4 h | Fryst |
| Vald horisont 2,5 h, start om 3 h | Flyttbar |
| Vald horisont 8 h, start om 6 h | Fryst |
| Vald horisont 0 h, start senare än nu | Flyttbar |
| Vald horisont 0 h, start vid eller före nu | Fortfarande fryst |

Övriga frysningsorsaker gäller oavsett valt värde. Noll stänger endast av
framtida låshorisont, inte status-, data- eller redan-påbörjad-låsning.

## Spårbarhet och leverans

Visa använd låshorisont i körloggen och sammanfattningen i appen/Excel.
Radkommentarer för låsta order anger den faktiskt använda horisonten.
Resultatfilernas versionsmarkör är `_v6_resultat_` i stället för `_v5_resultat_`.
V5-filer och V5:s SQL-tjänst ändras inte.

## Acceptanskriterier

Testa standardvärde 4, annan heltalshorisont, decimaler, noll och exakt
gränstid. Avvisa negativa, tomma, icke-numeriska och oändliga värden före
körning. Kontrollera att två körningar med olika värden inte påverkar varandra,
att inställningen sparas och att V5:s säkerhetsregler fortfarande fungerar.

Start och användning beskrivs i [README_v6.md](README_v6.md).