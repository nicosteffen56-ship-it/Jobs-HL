#!/usr/bin/env python3
"""Baut docs/index.html mit allen aktuellen Stellen (mobil-optimiert)."""
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import jobagent as j


def main() -> None:
    stellen = j.alle_stellen()
    for s in stellen:
        text = j.beschreibung(s["refnr"])
        treffer = [w for w in j.WARNWOERTER if w in text]
        if treffer:
            s["warnung"] = "Schicht/Nacht erwähnt: " + ", ".join(treffer)
        time.sleep(0.3)
    stellen.sort(key=lambda x: (bool(x["warnung"]), -x["punkte"]))

    stand = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")
    karten = []
    for s in stellen:
        warn = f"<div class='w'>⚠ {s['warnung']}</div>" if s["warnung"] else ""
        karten.append(
            f"<a class='k' href='{s['link']}'><b>{s['titel']}</b>{warn}"
            f"<span>{s['arbeitgeber']}</span>"
            f"<small>{s['ort']} · {s['datum']} · Passung {s['punkte']}</small></a>"
        )
    html = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Jobs Lübeck</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px;background:#f5f5f7;color:#111}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0 0 14px;color:#666;font-size:13px}}
.k{{display:block;background:#fff;border-radius:12px;padding:12px;margin-bottom:10px;text-decoration:none;color:inherit}}
.k span{{display:block;margin-top:2px}} .k small{{color:#666}} .w{{color:#c60;font-size:13px;margin-top:2px}}
@media(prefers-color-scheme:dark){{body{{background:#000;color:#eee}}.k{{background:#1c1c1e}}p,.k small{{color:#999}}}}
</style></head><body>
<h1>{len(stellen)} Stellen · {j.WO} {j.UMKREIS_KM} km</h1>
<p>Stand: {stand} (aktualisiert sich täglich)</p>
{''.join(karten) or '<p>Keine Treffer.</p>'}
</body></html>"""
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(html, encoding="utf-8")
    print(f"{len(stellen)} Stellen geschrieben.")


if __name__ == "__main__":
    main()
