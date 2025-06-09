#!/usr/bin/env python3
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request 
from pathlib import Path
import shutil, subprocess, textwrap
from analyzer.finalgoodanaliz import PROMPT_SYSTEMOWY
from webui.filtered import router as filtered
from ast import literal_eval
import re
import ast
import sys

app = FastAPI()

BASE   = Path(__file__).resolve().parent
ROOT   = BASE.parent
UPLOAD = BASE / "uploads"
STATIC = BASE / "static"
RESULT = STATIC / "results"
for d in (UPLOAD, RESULT): d.mkdir(parents=True, exist_ok=True)

SCRIPT = Path(__file__).parent.parent / "analyzer" / "finalgoodanaliz.py"
sys.path.append(str(Path(__file__).parent.parent))
 

app.include_router(filtered)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def replace_line(file: Path, prefix: str, new_line: str):
    lines = file.read_text("utf-8").splitlines()
    lines = [ln for ln in lines if not ln.lstrip().startswith(prefix)]
    insert_at = 0
    for i, ln in enumerate(lines):
        if not (ln.startswith("import") or ln.startswith("from") or ln.startswith("#") or not ln.strip()):
            insert_at = i
            break
    lines.insert(insert_at, new_line)
    file.write_text("\n".join(lines), encoding="utf-8")

def update_prompt(file: Path, prompt: str):
    safe = textwrap.dedent(prompt).replace('"', r'\\"')  # экранируем кавычки
    lines = safe.splitlines()

    multiline = "PROMPT_SYSTEMOWY = (\n" + "\n".join(f'    "{line}\\n"' for line in lines) + "\n)"

    replace_line(file, "PROMPT_SYSTEMOWY =", multiline)

def get_installed_models() -> list[str]:
    try:
        output = subprocess.check_output(["ollama", "list"], text=True)
        lines = output.strip().splitlines()[1:]  # Skip header
        models = [line.split()[0] for line in lines if line.strip()]
        return models
    except Exception as e:
        print("Błąd przy pobieraniu modeli:", e)
        return []

def _read_current_prompt():
    path = Path(__file__).parent.parent / "finalgoodanaliz.py"
    content = path.read_text(encoding="utf-8")

    try:
        match = re.search(r'PROMPT_SYSTEMOWY\s*=\s*\((.*?)\)', content, re.DOTALL)
        if not match:
            return ""
        value_str = "(" + match.group(1) + ")"
        return ast.literal_eval(value_str)
    except Exception as e:
        print(f"❌ Błąd parsowania PROMPT_SYSTEMOWY: {e}")
        return ""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "models": get_installed_models(),
        "default_prompt": PROMPT_SYSTEMOWY
    })

@app.post("/analyze")
async def analyze(request: Request,
                  model:  str        = Form(...),
                  date:   str        = Form(...),
                  prompt: str        = Form(""),
                  plik:   UploadFile = File(...)):

    dest_file = UPLOAD / plik.filename
    with dest_file.open("wb") as f:
        shutil.copyfileobj(plik.file, f)

    replace_line(SCRIPT, "MODEL =",      f'MODEL = "{model}"')
    replace_line(SCRIPT, "PLIK_LOGOW =", f'PLIK_LOGOW = Path(r"{dest_file}")')
    if prompt.strip():
        Path(SCRIPT.parent / "prompt.txt").write_text(prompt, encoding="utf-8")

    try:
        subprocess.run(["python3", str(SCRIPT), date], check=True)
    except subprocess.CalledProcessError as e:
        return HTMLResponse(f"<h3>Błąd: analiza nie powiodła się.<br><pre>{e}</pre></h3>", status_code=500)

    html = RESULT / f"triage_{date}.html"
    if html.exists():
        return RedirectResponse(f"/static/results/{html.name}", status_code=303)

    return HTMLResponse("<h3>Błąd: raport nie został wygenerowany.</h3>", status_code=500)

