# 🕵️‍♂️ AI Log Analyzer (Ollama + Web UI)

A Python-based tool for analyzing security logs using a local AI model via Ollama. It filters logs by date, splits them into batches, sends them to the model, and outputs grouped results in JSON and HTML formats.

---

## 🚀 Features

- 📅 Filter logs by date (`timestamp`)
- 🧠 Analyze logs with a local LLM (via Ollama)
- 🧹 Group results by `komputer` and `reason`
- 📄 Export JSON and beautiful HTML report
- 🌐 Easy-to-use web interface with prompt editing, model selection, and log upload

---

## 🛠️ Setup and Launch

### 1.
```bash
pip install -r requirements.txt
ollama serve
uvicorn webui.app:app 

