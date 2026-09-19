import os
from pathlib import Path

import chess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from models import AnalyzeRequest, AnalyzeResponse
from engine import engine_analysis
from grounding import GroundedLLM


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Whyfish API",
    description="Chess analysis with grounded explanations",
    version="1.0.0",
)

ALLOW_MOCK_ENGINE = (
    os.environ.get("WHYFISH_ALLOW_MOCK_ENGINE", "0") == "1"
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

def get_frontend_file(filename: str) -> Path:
    path = BASE_DIR / filename

    if not path.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"Frontend file missing: {filename}",
        )

    return path


@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(
        get_frontend_file("index.html"),
        media_type="text/html",
    )


@app.get("/index.html", include_in_schema=False)
async def serve_index_html():
    return FileResponse(
        get_frontend_file("index.html"),
        media_type="text/html",
    )


@app.get("/analysis.html", include_in_schema=False)
async def serve_analysis():
    return FileResponse(
        get_frontend_file("analysis.html"),
        media_type="text/html",
    )


@app.get("/about.html", include_in_schema=False)
async def serve_about():
    return FileResponse(
        get_frontend_file("about.html"),
        media_type="text/html",
    )


@app.get("/style.css", include_in_schema=False)
async def serve_stylesheet():
    return FileResponse(
        get_frontend_file("style.css"),
        media_type="text/css",
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("shutdown")
async def shutdown_event():
    engine_analysis.stop_engine()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_request(request: AnalyzeRequest) -> chess.Board:
    try:
        board = chess.Board(request.fen)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid FEN: {exc}",
        )

    if request.human_move:
        try:
            move = chess.Move.from_uci(request.human_move)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid human_move. Expected UCI notation, "
                    "for example e2e4 or g1f3."
                ),
            )

        if move not in board.legal_moves:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Illegal human_move '{request.human_move}' "
                    "for the supplied position."
                ),
            )

    return board


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------

async def _run_grounded_pipeline(
    request: AnalyzeRequest,
) -> AnalyzeResponse:

    validate_request(request)

    try:
        analysis = engine_analysis.analyze_position(
            request.fen,
            request.human_move,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unexpected Stockfish analysis failure.",
        ) from exc

    if (
        analysis.get("engine_source") == "mock"
        and not ALLOW_MOCK_ENGINE
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Analysis engine unavailable: Stockfish binary not found. "
                "Install Stockfish or set WHYFISH_ALLOW_MOCK_ENGINE=1 "
                "for local development only."
            ),
        )

    api_key = os.environ.get("GROQ_API_KEY", "").strip()

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY not configured.",
        )

    try:
        llm = GroundedLLM(api_key=api_key)

        return llm.analyze_with_grounding(
            analysis,
            request.fen,
            request.human_move,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Grounded explanation failed: {exc}",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Grounded explanation service failed.",
        ) from exc


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post(
    "/api/analyze",
    response_model=AnalyzeResponse,
)
async def analyze_position(
    request: AnalyzeRequest,
):
    return await _run_grounded_pipeline(request)


@app.post(
    "/api/grounded-analyze",
    response_model=AnalyzeResponse,
)
async def grounded_analyze_position(
    request: AnalyzeRequest,
):
    return await _run_grounded_pipeline(request)

@app.get("/api/presets")
async def get_presets():
    return [
        {
            "name": "Starting Position",
            "fen": (
                "rnbqkbnr/pppppppp/8/8/"
                "8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            ),
            "description": "Standard chess starting position.",
        },
        {
            "name": "Scholar's Mate Threat",
            "fen": (
                "r1bqkbnr/pppp1ppp/2n5/4p2Q/"
                "2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
            ),
            "description": (
                "White's queen and bishop target f7, creating an immediate "
                "Scholar's Mate threat."
            ),
        },
        {
            "name": "Back Rank Mate",
            "fen": (
                "6k1/5ppp/8/8/8/8/"
                "5PPP/3R2K1 w - - 0 1"
            ),
            "description": (
                "White can exploit Black's restricted king with a back-rank mate."
            ),
        },
        {
            "name": "Fool's Mate Threat",
            "fen": (
                "rnbqkbnr/pppp1ppp/8/4p3/"
                "6P1/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2"
            ),
            "description": (
                "Black can exploit White's weakened kingside with Qh4+."
            ),
        },
        {
            "name": "Tactical Knight Fork",
            "fen": (
                "2r3k1/pp3ppp/8/3N4/"
                "8/8/PP3PPP/6K1 w - - 0 1"
            ),
            "description": (
                "White can play Ne7+, forking the king and Black's rook."
            ),
        },
    ]
# ---------------------------------------------------------------------------
# Local execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )