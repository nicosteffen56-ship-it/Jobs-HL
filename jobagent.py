#!/usr/bin/env python3
"""
Job-Agent: durchsucht täglich die Jobbörse der Bundesagentur für Arbeit
(Umkreis 25 km um Lübeck) und mailt nur NEUE passende Stellen.

Setup:
  pip install requests
  Umgebungsvariablen setzen: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO
  Test ohne Mail:  python jobagent.py --dry-run
  Täglich (cron):  0 7 * * * cd /pfad/zum/skript && /usr/bin/python3 jobagent.py
"""
import argparse
import base64
import json
import os
import smtplib
import ssl
import time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

# ---------------------------------------------------------------- Einstellungen
WO = "Lübeck"
UMKREIS_KM = 25
MAX_ALTER_TAGE = 14          # nur Stellen der letzten X Tage
SEEN_FILE = Path(__file__).with_name("seen.json")

# Suchbegriffe: (Begriff, Punkte für die Passung)
SUCHBEGRIFFE = [
    ("Zahnmedizinische Fachangestellte", 5),
    ("Zahnarzthelferin", 5),
    ("Praxisrezeption", 4),
    ("Medizinische Fachangestellte Anmeldung", 4),
    ("Empfang Praxis", 3),
    ("Verwaltungsassistenz", 3),
    ("Sachbearbeiter Kundenservice", 2),
    ("Sekretariat", 2),
    ("Disposition Zustellung", 3),
    ("Zustellkoordination", 3),
    ("Patientenaufnahme", 3),
    ("Bürokraft", 2),
]

# Wenn im TITEL -> Stelle wird verworfen
AUSSCHLUSS_TITEL = ["schicht", "nacht", "wechselschicht", "bereitschaft", "24/7"]
# Wenn in der Beschreibung -> Stelle bleibt, bekommt aber eine Warnung
WARNWOERTER = ["schichtdienst", "wechselschicht", "nachtdienst", "nachtschicht",
               "wochenenddienst", "bereitschaftsdienst", "im schichtbetrieb"]
# Bonuspunkte, wenn im Titel/Beruf
BONUS = {"teilzeit": 1, "vollzeit": 1, "quereinsteiger": 2, "quereinstieg": 2,
         "zahn": 2, "rezeption": 1, "empfang": 1}

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4"
HEADERS = {"X-API-Key": "jobboerse-jobsuche", "User-Agent": "jobagent/1.0"}


# ---------------------------------------------------------------- Suche
def suche(begriff: str) -> list[dict]:
    treffer = []
    for page in (1, 2):
        params = {
            "was": begriff,
            "wo": WO,
            "umkreis": UMKREIS_KM,
            "angebotsart": 1,               # 1 = Arbeit
            "veroeffentlichtseit": MAX_ALTER_TAGE,
            "size": 50,
            "page": page,
        }
        r = requests.get(f"{BASE}/jobs", headers=HEADERS, params=params, timeout=30)
        r.raise_for_status()
        liste = r.json().get("stellenangebote", [])
        treffer += liste
        if len(liste) < 50:
            break
        time.sleep(0.5)
    return treffer


def beschreibung(refnr: str) -> str:
    """Volltext der Stelle (für Schicht-Warnung). Fehler sind unkritisch."""
    try:
        ref = base64.b64encode(refnr.encode()).decode()
        r = requests.get(f"{BASE}/jobdetails/{ref}", headers=HEADERS, timeout=30)
        r.raise_for_status()
        return (r.json().get("stellenbeschreibung") or "").lower()
    except Exception:
        return ""


# ---------------------------------------------------------------- Bewertung
def bewerten(job: dict, basis_punkte: int) -> dict | None:
    titel = (job.get("titel") or "")
    beruf = (job.get("beruf") or "")
    text = f"{titel} {beruf}".lower()
    if any(w in text for w in AUSSCHLUSS_TITEL):
        return None
    punkte = basis_punkte + sum(p for w, p in BONUS.items() if w in text)
    ort = job.get("arbeitsort", {}) or {}
    refnr = job["refnr"]
    return {
        "refnr": refnr,
        "titel": titel,
        "arbeitgeber": job.get("arbeitgeber", "k. A."),
        "ort": f"{ort.get('plz', '')} {ort.get('ort', '')}".strip(),
        "datum": job.get("aktuelleVeroeffentlichungsdatum", ""),
        "link": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}",
        "punkte": punkte,
        "warnung": "",
    }


def alle_stellen() -> list[dict]:
    gefunden: dict[str, dict] = {}
    for begriff, basis in SUCHBEGRIFFE:
        try:
            for job in suche(begriff):
                b = bewerten(job, basis)
                if b is None:
                    continue
                alt = gefunden.get(b["refnr"])
                if alt is None or b["punkte"] > alt["punkte"]:
                    gefunden[b["refnr"]] = b
        except Exception as e:
            print(f"Fehler bei '{begriff}': {e}")
        time.sleep(0.5)
    return sorted(gefunden.values(), key=lambda j: j["punkte"], reverse=True)


# ---------------------------------------------------------------- Mail
def html_mail(stellen: list[dict]) -> str:
    zeilen = []
    for s in stellen:
        warn = f" <b style='color:#c60'>⚠ {s['warnung']}</b>" if s["warnung"] else ""
        zeilen.append(
            f"<li><a href='{s['link']}'><b>{s['titel']}</b></a>{warn}<br>"
            f"{s['arbeitgeber']} · {s['ort']} · veröffentlicht {s['datum']} "
            f"· Passung {s['punkte']}</li><br>"
        )
    return (f"<h3>{len(stellen)} neue Stellen im Umkreis von {UMKREIS_KM} km um {WO}</h3>"
            f"<ul>{''.join(zeilen)}</ul>")


def sende_mail(stellen: list[dict]) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Jobagent {date.today():%d.%m.%Y}: {len(stellen)} neue Stellen"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]
    msg.attach(MIMEText(html_mail(stellen), "html", "utf-8"))
    port = int(os.environ.get("SMTP_PORT", "465"))
    host = os.environ["SMTP_HOST"]
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.send_message(msg)


# ---------------------------------------------------------------- Main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="nicht mailen, nur ausgeben")
    args = ap.parse_args()

    gesehen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    neue = [s for s in alle_stellen() if s["refnr"] not in gesehen]

    # Schicht-Warnung nur für neue Stellen prüfen (spart Anfragen)
    for s in neue:
        text = beschreibung(s["refnr"])
        treffer = [w for w in WARNWOERTER if w in text]
        if treffer:
            s["warnung"] = "Schicht/Nacht erwähnt: " + ", ".join(treffer)
        time.sleep(0.3)
    neue.sort(key=lambda j: (bool(j["warnung"]), -j["punkte"]))  # Warnungen ans Ende

    if not neue:
        print("Keine neuen Stellen.")
        return
    if args.dry_run:
        for s in neue:
            print(f"[{s['punkte']}] {s['titel']} | {s['arbeitgeber']} | {s['ort']} | "
                  f"{s['link']} {s['warnung']}")
        return
    sende_mail(neue)
    SEEN_FILE.write_text(json.dumps(sorted(gesehen | {s["refnr"] for s in neue})))
    print(f"{len(neue)} Stellen gemailt.")


if __name__ == "__main__":
    main()
