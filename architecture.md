# WhyFish architecture

WhyFish uses Stockfish for chess calculation and Groq for converting structured engine evidence into a human-readable explanation. The LLM does not independently determine the best move or analyze the position — it receives Stockfish's output and explains it, and its structured evidence references are mechanically checked against that output before the response reaches the browser.

## Request lifecycle

```
Browser (index.html / analysis.html)
        |
        |  POST /api/analyze  { fen, human_move }
        v
FastAPI (main.py)
        |  validate_request(): FEN via python-chess, human_move must be
        |  legal UCI for that position, else 400
        v
_run_grounded_pipeline()
        |
        v
Stockfish engine (engine.py)
        |  engine_analysis.analyze_position(fen, human_move)
        |  returns: best_line, eval_cp, human_line, human_eval,
        |           key_squares, engine_source
        v
Grounding (grounding.py)
        |  build_grounding_prompt(): constrains the LLM to only cite
        |  moves/squares that appear in the Stockfish output above
        v
Groq API (openai/gpt-oss-120b)
        |  strict-mode JSON Schema first (constrained decoding)
        |  falls back to best-effort JSON object mode, then brace
        |  extraction, if strict mode fails
        v
Validator (_validate_llm_output, inside grounding.py)
        |  drops any step whose move_uci isn't in best_line/human_line,
        |  or whose highlight_squares aren't a subset of key_squares
        v
Response schema (models.py)
        |  AnalyzeResponse: best_move, eval_cp, explanation_steps,
        |  human_move_comparison, engine_source
        v
Browser renders steps, eval, and human-move comparison
```

## Files and responsibilities

| File | Responsibility |
|---|---|
| `index.html` | FEN input, optional UCI human-move input (client-side format check only), preset buttons, writes to `sessionStorage`, navigates to `analysis.html` |
| `analysis.html` | Reads `sessionStorage`, calls `/api/analyze`, renders `explanation_steps` (with `move_uci` badges), `human_move_comparison`, and surfaces backend error `detail` messages for 400/500/502/503 |
| `main.py` | Serves the frontend files directly (`FileResponse`), validates requests, orchestrates the pipeline in `_run_grounded_pipeline`, exposes `/api/analyze` and `/api/grounded-analyze` as aliases of the same pipeline, and `/api/presets` |
| `engine.py` | Wraps `python-chess` + Stockfish via UCI. Runs the position once for the best line, and again after the human's move (if given) to get a directly comparable `human_eval`. Falls back to `_mock_analysis()` only if Stockfish isn't found, and always reports which via `engine_source` |
| `grounding.py` | `GroundedLLM` class: builds the constrained prompt, calls Groq, validates the response against the Stockfish data, and assembles the final `AnalyzeResponse` |
| `models.py` | Pydantic schemas shared by the backend and (implicitly) the frontend's expectations of the JSON shape |
| `Dockerfile` | Bakes Stockfish into the container alongside the Python app for deployment |

## Core design decisions

**Stockfish is the sole source of chess calculation.** It produces the best line, evaluation, human-move evaluation and continuation, and key squares. Groq never independently analyzes the position — it receives this structured evidence and converts it into prose. If asked directly: no, the LLM is not analyzing the chess position; Stockfish already did, and the LLM explains the result.

**Grounding is enforced by structured validation, not by the prompt alone, and the guarantee is narrower than "every claim is verified."** The prompt asks the LLM to cite moves via a structured `move_uci` field (not embedded in prose) and to keep `highlight_squares` within the reported key squares. `_validate_llm_output` checks exactly those two structured fields — `move_uci ∈ best_line ∪ human_line` and `highlight_squares ⊆ key_squares` — and drops any step that fails either check, no partial credit. What this does *not* do is verify the free-text `text` field itself: a step can cite a real move and real squares while still describing them with a claim the validator has no way to check. The accurate framing is "the structured evidence a step references is mechanically validated against Stockfish output," not "every generated sentence is proven."

**`human_eval` is computed by re-analyzing the position after the human's move**, then negating the score (Stockfish reports `.relative` from the side-to-move's perspective, which is the opponent immediately after the human moves). This is what makes `eval_swing_cp` in `HumanMoveComparison` a real, well-defined number from actual engine analysis, not an LLM estimate.

**Mock Stockfish data can never silently reach the client as a real response.** `engine.py` always reports `engine_source` ("stockfish" or "mock"), and `main.py` returns a `503` if the source is "mock" unless `WHYFISH_ALLOW_MOCK_ENGINE=1` is explicitly set — intended for local frontend-wiring work only, never for a demo or deployment.

**`/api/analyze` and `/api/grounded-analyze` are the same pipeline.** There is no placeholder path left; both routes call `_run_grounded_pipeline` directly.

## LLM configuration

Provider: Groq. Model: `openai/gpt-oss-120b`, a reasoning model whose hidden chain-of-thought tokens share the same budget as the visible JSON answer. This requires `max_completion_tokens=4096` and `reasoning_effort="low"`, or the model can exhaust its budget reasoning and return an empty completion that fails JSON validation with a misleading, contentless error.

The request tries strict-mode JSON Schema first (constrained decoding), then falls back to best-effort JSON object mode, then brace extraction if that also fails. Either way, the response still passes through the same validator before being returned.

## Known follow-ups

- Full browser UI test of the round trip (only tested via direct API calls so far)
- Board/move visualization beyond static square highlighting
- A small set of verified-good demo positions for presentation day
- Docker rebuild/test since dependencies changed (Groq added, Anthropic/OpenAI no longer used)
- Deployment to a public host with `GROQ_API_KEY` set as a platform secret

## Provider history

Kept here rather than deleted, since the comments in `grounding.py` reference this directly and a reader shouldn't have to guess why.

- **Original**: Anthropic Claude — worked, abandoned after running out of API credit mid-hackathon.
- **Groq, `llama-3.3-70b-versatile`** — worked initially, then the model was decommissioned by Groq (2026-08-16).
- **Groq, `openai/gpt-oss-120b`** (current) — works; see LLM configuration above for the reasoning-token caveat.
- **Snowflake Cortex, `deepseek-ai/deepseek-v3.1`** — evaluated as a cost alternative, not pursued: blocked outright with `AI function COMPLETE is not available for trial accounts`, confirmed directly against the account. Not a configuration issue; no self-service unlock found.