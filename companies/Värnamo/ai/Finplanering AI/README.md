# AI Omplanering — Op10

Planerar om Operation 10 för tillverkningsorder ur Jeeves ERP. Den samlade
lösningskontexten och de styrande reglerna för V5–V7 finns i
[instuktion.md](instuktion.md). Denna README beskriver den icke
versionssuffixerade grundappen; V7 har egna README-filer och implementation.

## Filer

| Fil | Roll |
|---|---|
| `omplanering_app.py` | Skrivbordsapp (Tkinter). Välj fil → Kör → resultat. **Starta här.** |
| `omplanering_core.py` | Beräkningsmotorn. Fristående från UI:t, går även att köra från terminal eller importera. |
| `dokumentation.html` | Fullständig dokumentation — dataflöde, regelverk i verksamhets- och teknikspår, kalenderlogik, utdataformat, antaganden. |
| `output/` | Tidsstämplade leveransfiler (`.xlsx` + `.csv`). Inget skrivs över. |

## Versionsseparerade appar

V5, V6, V7 och V8 finns som separata appar och implementationer. V8 lägger till
Excel/SQL Server som valbara datakällor, en valfri bekräftad uppdateringsprocedur
och uttryckligen bekräftad resultatskrivning till SQL. Se [README_v8.md](README_v8.md)
för lokal konfiguration, Windows-installerare, tester och GitHub Releases.

## Köra

Appen:

```bash
python omplanering_app.py
```

Terminal:

```bash
python omplanering_core.py "AI omplanering.xlsx" -o output
```

Som bibliotek:

```python
import omplanering_core as core
res = core.run_replanning("AI omplanering.xlsx")
res.stats["red_before"], res.stats["red_after"]
```

## Kräver

Python 3.9 eller senare:

```bash
pip install -r requirements.txt
```

`tkinter` ingår i Python för Windows och behövs bara för appen – det
installeras inte via pip. På Windows är `tzdata` obligatorisk: operativsystemet
saknar tidszonsdatabas, så `ZoneInfo("Europe/Stockholm")` i frysningsregeln
faller tillbaka på det paketet.

För SQL-tjänsten, se [service/README.md](service/README.md) – den behöver
också `pyodbc`.

## Utdata

Per körning skapas två filer i utkatalogen:

- `<filnamn>_resultat_<yyyyMMddHHmmss>.xlsx` — de fyra källflikarna oförändrade
  plus `tblAIAnglysisGetAoColorCodeList` (radfärgad, frysta rubriker, autofilter)
  och `AI_Sammanfattning`.
- `<filnamn>_resultat_<yyyyMMddHHmmss>.csv` — resultattabellen semikolonavgränsad
  för databasimport.

Se `dokumentation.html` för kolumnbeskrivningar, regelverk och antaganden.
