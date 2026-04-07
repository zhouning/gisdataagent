# Quick Start Guide

## Option 1: Docker (Recommended)

```bash
# 1. Clone
git clone https://github.com/zhouning/gisdataagent.git
cd gisdataagent

# 2. Configure
cp .env.example data_agent/.env
# Edit data_agent/.env — set GOOGLE_API_KEY or Vertex AI credentials

# 3. Build frontend
cd frontend && npm install && npm run build && cd ..

# 4. Start (PostGIS + App + Redis)
docker compose up -d

# 5. Open browser
# http://localhost:8000
# Login: admin / admin123
```

### With QC subsystems (optional)
```bash
docker compose --profile qc up -d
```

### With vector tile server (optional)
```bash
docker compose --profile tiles up -d
```

## Option 2: Local Development (Windows)

### Prerequisites
- Python 3.13+ (Anaconda recommended)
- PostgreSQL 16 + PostGIS 3.4
- Node.js 20+

### Setup
```powershell
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example data_agent\.env
# Edit data_agent\.env — set database credentials + API keys

# 4. Build frontend
cd frontend
npm install
npm run build
cd ..

# 5. Run
$env:PYTHONPATH = "D:\adk"
chainlit run data_agent/app.py -w
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_HOST` | Yes | Database host (`db` in Docker, `localhost` local) |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `GOOGLE_API_KEY` | Yes* | Google AI API key (*or use Vertex AI) |
| `CHAINLIT_AUTH_SECRET` | Yes | Session secret (`chainlit create-secret`) |
| `GAODE_API_KEY` | No | Gaode Maps geocoding |
| `TIANDITU_TOKEN` | No | Tianditu basemap |

See `.env.example` for all options.

## Verify Installation

```bash
# Run QC demo (no DB/LLM required)
python scripts/demo_qc.py

# Run tests
python -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q
```

## Architecture

```
Browser → Chainlit (8000) → ADK Agents → PostGIS (5432)
                ↕                           ↕
         React SPA              Redis (6379, optional)
         3 panels               Martin tiles (3000, optional)
```

**Three pipelines**: Optimization (DRL) | Governance (QC) | General (analysis)

**Login**: `admin` / `admin123` (auto-seeded on first run)
