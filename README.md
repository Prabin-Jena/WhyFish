# Whyfish ♞

> **Stockfish knows what. Whyfish explains why.**

Whyfish takes a chess position and uses Stockfish's real calculations to generate human-readable tactical explanations strictly grounded in the engine's verified telemetry.

---

## Features

- **Grounded Chess Analysis**: Every explanation step cites mechanically validated coordinates and moves from Stockfish's candidate lines.
- **Explain My Move**: Compare your proposed move against the engine's recommendation with live evaluation swings and refutations.
- **Interactive Move Replay**: Animated piece transitions and a 4-button navigation system (Previous, Play, Pause, Next) with auto-advance.
- **Curated Demo Scenarios**: 1-click curated scenarios (Tactical Fork, Back Rank Mate, Scholar's Mate, Fool's Mate) for immediate evaluation without typing a FEN.
- **Dark & Light Motion System**: Elegant editorial typography with persistent theme toggle and reduced-motion accessibility.

---

## Deployment (Render)

Whyfish runs as a single Docker container serving the FastAPI backend, Stockfish binary, and static frontend assets.

### 1. Push to GitHub
```bash
git remote add origin https://github.com/<YOUR_USERNAME>/WhyFish.git
git push -u origin main
```

### 2. Create Render Web Service
1. Log into [Render](https://render.com)
2. Click **New +** → **Web Service**
3. Select your **WhyFish** GitHub repository
4. Settings:
   - **Environment**: `Docker`
   - **Branch**: `main`
   - **Region**: Closest to your users (e.g., Oregon or Frankfurt)
   - **Plan**: `Free`
5. Environment Variables:
   - `GROQ_API_KEY` = `your_groq_api_key_here`
6. Click **Create Web Service**. Render will build the Docker container and deploy it automatically.

> **Note on Free Tier**: Render spins down free containers after 15 minutes of inactivity. The first request upon waking will take ~30–40 seconds. Keep the tab open or send a ping before presentation/judging.

---

## Local Docker Run

### Build Image
```bash
docker build -t whyfish .
```

### Run Container
```bash
docker run -p 8000:8000 -e GROQ_API_KEY="your_groq_api_key_here" whyfish
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Local Python Development

### Requirements
- Python 3.11+
- Stockfish binary installed on system `PATH` (or in `/usr/games/stockfish`)

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

- `GET /` — Serves landing page
- `GET /analysis.html` — Interactive analysis dashboard
- `GET /about.html` — Architecture & methodology explanation
- `GET /api/presets` — Curated demo chess scenarios
- `POST /api/analyze` — Run grounded analysis (`{"fen": "...", "human_move": "..."}`)