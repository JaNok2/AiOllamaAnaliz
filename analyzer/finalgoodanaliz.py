#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

import argparse
import json
import sys
import time
import http.client
import urllib.parse
from datetime import datetime, date
from dateutil import parser as dt_parser
from collections import defaultdict


# ───── katalogi projektu ──────────────────────────────────────────────────
PLIK_LOGOW = Path(r"/Users/jan/Desktop/trash/AiAnaliz/AiAnalizLocal/webui/uploads/filtered_download.json")
MODEL = "mistral-temp:latest"
PROMPT_PATH = Path(__file__).parent / "prompt.txt"
PROMPT_SYSTEMOWY = PROMPT_PATH.read_text(encoding="utf-8")


STATIC_DIR = Path(__file__).resolve().parent.parent / "webui" / "static"
BASE_DIR = Path(__file__).resolve().parent 

OUT_DIR = STATIC_DIR / "results"
BAD_DIR = STATIC_DIR / "bad"
            
for d in (OUT_DIR, BAD_DIR):
    d.mkdir(exist_ok=True)


OLLAMA_URL  = "http://localhost:11434/api/generate"
TIMEOUT     = 50
RETRIES     = 2
DOMYŚLNA_PACZKA = 9

def parse_time(ts: str) -> datetime:
    return dt_parser.isoparse(ts).astimezone(tz=None).replace(tzinfo=None)


def iter_logs(path: Path):
    with path.open(encoding="utf-8", errors="replace") as fh:
        first_line = fh.readline().strip()
        if first_line.startswith("["):  #JSON-array
            try:
                data = json.loads(first_line + "".join(fh))
                for entry in data:
                    yield entry
                return
            except Exception:
                pass  

        #JSONL
        try:
            entry = json.loads(first_line)
            yield entry
        except Exception:
            pass

        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

def iter_logs_for_day(path: Path, target: date):
    for entry in iter_logs(path):
        ts = entry.get("timestamp")
        if not ts:
            continue
        try:
            if parse_time(ts).date() == target:
                yield entry
        except Exception:
            continue

def clean_log(entry: dict) -> dict:
    if isinstance(entry.get("message"), str):
        entry["message"] = entry["message"][:300].replace("\n", " ")
    for pole in ("full_log", "data", "decoder", "fields", "location"):
        entry.pop(pole, None)
    return entry


def build_prompt(logs: list[dict]) -> str:
    return PROMPT_SYSTEMOWY + "\n\n" + json.dumps({"logs": [clean_log(l.copy()) for l in logs]}, ensure_ascii=False)


def _http_conn(url):
    return http.client.HTTPConnection(url.hostname, url.port, timeout=TIMEOUT)


# ---------------  parse_ollama_response  ----------------
def parse_ollama_response(raw: str) -> list[dict]:
    if not raw.strip():
        raise RuntimeError("Ollama zwróciła pusty tekst.")

    try:
        obj = json.loads(raw)                 # stream=False
        tekst = obj.get("response", "").strip()
    except json.JSONDecodeError:
        # stream=True – każda linia to JSON z polem "response"
        fragments = []
        for ln in raw.splitlines():
            try:
                part = json.loads(ln)
            except Exception:
                continue
            if part.get("done"):
                break
            if "response" in part:
                fragments.append(part["response"])
        tekst = "".join(fragments).strip()

    # usuń ewentualny ```json ... ``` code-block
    if tekst.startswith("```"):
        tekst = tekst.strip("` ").lstrip("json").strip()

    # spróbuj rozkodować tekst do listy
    try:
        wynik = json.loads(tekst)
        if isinstance(wynik, list):
            return wynik
    except Exception:
        pass

    bad_file = BAD_DIR / f"ollama_bad_{int(time.time())}.txt"
    bad_file.write_text(raw, encoding="utf-8")

    raise RuntimeError(
        f"Odpowiedź Ollama nie jest poprawną listą. "
        f"Surowy tekst zapisano w: {bad_file}"
    )


def send_prompt(prompt: str, retries: int = RETRIES) -> list[dict]:
    url = urllib.parse.urlparse(OLLAMA_URL)
    for attempt in range(1, retries + 1):
        conn = None
        try:
            conn = _http_conn(url)
            body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False})
            conn.request("POST", url.path, body=body, headers={"Content-Type": "application/json"})
            raw = conn.getresponse().read().decode("utf-8")
            return parse_ollama_response(raw)
        except Exception as exc:
            if attempt >= retries:
                raise RuntimeError(f"Zapytanie nie powiodło się: {exc}") from exc
            print(f"⚠️  Próba {attempt} nieudana ({exc}). Повтор через {2**attempt}s…")
            time.sleep(2 ** attempt)
        finally:
            if conn:
                conn.close()
    return []


def grupuj_logi(wyniki: list[dict]) -> list[dict]:
    grupy = defaultdict(list)
    policz_przyjete = 0
    policz_pominiete = 0

    for log in wyniki:
        if not isinstance(log, dict):
            policz_pominiete += 1
            continue
        if "komputer" not in log or "reason" not in log:
            policz_pominiete += 1
            continue
        klucz = (log["komputer"], log["reason"])
        grupy[klucz].append(log)
        policz_przyjete += 1

    print(f"ℹ️ Przyjęte do grupowania: {policz_przyjete}, pominięte: {policz_pominiete}")

    zgrupowane = []
    for (komputer, reason), logs in grupy.items():
        times = sorted((log.get("czas") or "") for log in logs if "czas" in log and log.get("czas"))
        if not times:
            times = ["brak czasu"]

        if len(logs) == 1:
            zgrupowane.append(logs[0])
        else:
            zgrupowane.append({
                "id": logs[0].get("id", "-"),
                "komputer": komputer,
                "czas": f"{times[0]} – {times[-1]}",
                "level": logs[0].get("level", "medium"),
                "reason": f"{len(logs)}× {reason}",
                "explain": f"Wykryto {len(logs)} podobnych zdarzeń na {komputer} między {times[0]} a {times[-1]}."
            })

    print(f"✅ Zgrupowane: {len(zgrupowane)} wpisów")
    return zgrupowane


def save_html(wyniki: list[dict], json_path: Path):
    html_path = json_path.with_suffix(".html")
    def level_color(level: str) -> str:
        return {
            "critical": "red",
            "high": "orangered",
            "medium": "orange",
            "low": "gray",
        }.get(str(level).lower(), "black")

    with html_path.open("w", encoding="utf-8") as f:
        f.write("<meta charset='utf-8'>\n")
        f.write(f"<h2>Ważne logi — {json_path.stem.split('_')[1]}</h2><ul>")
        for log in wyniki:
            lvl = str(log.get("level", "?")).lower()
            f.write("<li style='margin-bottom:1em'>")
            f.write(f"<b>Komputer:</b> {log.get('komputer','?')}<br>")
            f.write(f"<b>Poziom:</b> <span style='color:{level_color(lvl)}'>{lvl.upper()}</span><br>")
            f.write(f"<b>Powód:</b> {log.get('reason','')}<br>")
            f.write(f"<b>Opis:</b> {log.get('explain','')}<br>")
            f.write(f"<small>ID: {log.get('id','?')} | {log.get('czas','?')}</small>")
            f.write("</li>")
        f.write("</ul>")
    print(f"📝  Zapisano HTML: {html_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data", help="dzień RRRR‑MM‑DD")
    p.add_argument("--batch", "-b", type=int, default=DOMYŚLNA_PACZKA)
    args = p.parse_args()

    try:
        target_date = datetime.fromisoformat(args.data).date()
    except ValueError:
        sys.exit("✖️  Nieprawidłowa data (RRRR‑MM‑DD)")

    if not PLIK_LOGOW.exists():
        sys.exit(f"✖️  Nie znaleziono pliku: {PLIK_LOGOW}")

    logs = list(iter_logs_for_day(PLIK_LOGOW, target_date))
    if not logs:
        print("ℹ️  Brak logów na ten dzień.")
        return

    print(f"🔍  {len(logs)} logów. Paczka = {args.batch}")
    wyniki: list[dict] = []
    for i in range(0, len(logs), args.batch):
        part = logs[i:i + args.batch]
        prompt = build_prompt(part)
        print(f"⏳  Paczka {i + 1}‒{i + len(part)}…")
        try:
            resp = send_prompt(prompt)
            wyniki.extend(resp)
        except Exception as e:
            print(f"❌  Błąd paczki {(i // args.batch) + 1}: {e}")
            continue

    if not wyniki:
        print("ℹ️  LLM nie wskazał ważnych logów.")
        return

    wyniki = grupuj_logi(wyniki)

    json_path = OUT_DIR / f"triage_{target_date}.json"
    json_path.write_text(json.dumps(wyniki, indent=2, ensure_ascii=False))
    print(f"✅  Zapisano JSON: {json_path}")
    save_html(wyniki, json_path)


if __name__ == "__main__":
    main()