import json
import re
from groq import Groq
from typing import List, Optional, Dict
from models import AnalyzeRequest, AnalyzeResponse, AnalysisStep, HumanMoveComparison
from engine import EngineAnalysis

class GroundedLLM:
    # llama-3.3-70b-versatile was decommissioned by Groq on 2026-08-16.
    # openai/gpt-oss-120b is Groq's recommended replacement and additionally
    # supports strict-mode JSON Schema (constrained decoding) rather than only
    # best-effort JSON mode, which we use below for a stronger grounding guarantee.
    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b"):
        self.client = Groq(api_key=api_key)
        self.model = model

    def build_grounding_prompt(self, analysis: dict, fen: str, human_move: Optional[str] = None) -> str:
        """
        Build a system prompt + user prompt that constrains LLM to only reference
        moves and squares that actually appear in the Stockfish analysis.

        Each step must cite a single structured move_uci field (UCI format, e.g. "d1h5")
        rather than embedding move notation in free text — this is what makes the
        citation mechanically checkable in _validate_llm_output, instead of relying on
        regex against prose whose notation format the model may not follow.
        """
        best_line = analysis.get("best_line", [])
        human_line = analysis.get("human_line", [])
        key_squares = analysis.get("key_squares", [])
        eval_cp = analysis.get("eval_cp", 0)
        human_eval = analysis.get("human_eval")

        pv_moves = best_line[:5] if best_line else []
        human_pv_moves = human_line[:5] if human_line else []
        key_squares_info = ", ".join(key_squares[:5]) if key_squares else "none highlighted"

        # All UCI moves the model is allowed to cite via move_uci — both branches,
        # so it can explain the human line's continuation, not just the best line.
        allowed_moves = sorted(set(pv_moves) | set(human_pv_moves))

        human_section = ""
        if human_move:
            human_section = f"""
Human move played: {human_move}
Engine's continuation after the human move: {' '.join(human_pv_moves) if human_pv_moves else 'not available'}
Evaluation after human move: {human_eval if human_eval is not None else 'not available'} centipawns (from the human's own perspective)
Evaluation swing vs best move: {(eval_cp - human_eval) if human_eval is not None else 'not available'} centipawns"""

        prompt = f"""You are a chess analyst explaining why Stockfish recommends a specific move.

CRITICAL GROUNDING CONSTRAINT: You MUST only reference moves, squares, and evaluation changes that actually appear in the Stockfish analysis data below. Do NOT invent tactics, threats, or positional ideas that are not in the provided data.

Stockfish Analysis Data:
- Best line (UCI): {' '.join(pv_moves)}
- Evaluation after best move: {eval_cp} centipawns
- Key squares involved: {key_squares_info}
- Moves you are permitted to cite via move_uci: {', '.join(allowed_moves) if allowed_moves else 'none'}
{human_section}

Instructions:
1. Explain WHY the best move is good, referencing ONLY moves/squares from the Stockfish data above
2. If a human move was played, explain WHY it loses relative to the best move, using the engine's actual continuation and the evaluation swing given above — do not guess at a continuation
3. Output must be structured JSON with these fields:
   - "steps": array of {{ "text": string, "highlight_squares": array of square names, "move_uci": string or null }}
   - "text" should describe the idea in natural language, but the move being discussed in that step MUST also be given in "move_uci" using UCI notation (e.g. "d1h5") from the permitted moves list above — this is what makes the step verifiable. Use null only for a step that discusses no single move.
   - No free text outside this JSON structure
4. Each step's highlight_squares must be a subset of the key squares listed above
5. Each step's move_uci, if not null, must be exactly one of the permitted moves listed above

Explain the causal sequence: what specific tactical or positional ideas from the Stockfish analysis lead to the evaluation advantage.

JSON output only - do not include any explanation outside the JSON structure."""

        return prompt

    # JSON Schema for the expected LLM output shape. strict:true requires every
    # property to be listed in "required" and additionalProperties:false on every
    # object — that's a Groq/OpenAI structured-outputs constraint, not a style choice —
    # so highlight_squares/move_uci are "required" even though move_uci is nullable;
    # nullability is expressed via the type union, not by omitting it from required.
    _RESPONSE_SCHEMA = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "highlight_squares": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "move_uci": {"type": ["string", "null"]}
                    },
                    "required": ["text", "highlight_squares", "move_uci"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["steps"],
        "additionalProperties": False
    }

    def call_llm(self, prompt: str) -> dict:
        """
        Call the LLM with grounding constraint and parse structured response.

        openai/gpt-oss-120b is a reasoning model: its hidden chain-of-thought
        tokens draw from the SAME token budget as the visible JSON answer. With
        a too-small budget, the model can spend it all "thinking" and emit an
        empty completion, which both strict and best-effort JSON modes then
        reject as json_validate_failed with an empty failed_generation — this
        was reproduced directly against this model/prompt and is not a
        schema-shape issue. Fixed by (1) reasoning_effort="low" since this task
        is straightforward extraction/explanation, not deep reasoning, and
        (2) a much larger max_completion_tokens so the answer isn't starved
        even if some reasoning still happens.

        Tries strict-mode JSON Schema first (constrained decoding — the model is
        token-level restricted to the schema, so a malformed shape is essentially
        impossible when it succeeds). Falls back to best-effort JSON object mode
        if strict mode still fails for any other reason.
        """
        system_prompt = "You are a chess analyst. Output valid JSON matching the required schema. Each step has 'text' (string), 'highlight_squares' (array of square names), and 'move_uci' (a UCI move string like 'd1h5', or null)."

        strict_mode_error = None
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=4096,
                reasoning_effort="low",
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "whyfish_explanation",
                        "strict": True,
                        "schema": self._RESPONSE_SCHEMA
                    }
                },
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            text = completion.choices[0].message.content if completion.choices else ""
            if not text:
                raise ValueError("Strict-mode call returned an empty completion (likely reasoning-token exhaustion)")
            return json.loads(text)  # strict mode guarantees valid, schema-conformant JSON
        except Exception as e:
            # Don't swallow this silently — log it so a fallback failure below is
            # diagnosable instead of looking like the ONLY thing that went wrong.
            strict_mode_error = e
            print(f"[grounding] Strict-mode JSON Schema call failed, falling back to best-effort mode: {e}")

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=4096,
                reasoning_effort="low",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt + " Do not include any text outside the JSON."},
                    {"role": "user", "content": prompt}
                ]
            )
        except Exception as fallback_error:
            # Both modes failed — surface both errors, not just the second one,
            # so the actual root cause (often the strict-mode one) isn't hidden.
            raise ValueError(
                f"Both strict-mode and best-effort LLM calls failed. "
                f"Strict-mode error: {strict_mode_error}. "
                f"Best-effort error: {fallback_error}"
            )

        text = completion.choices[0].message.content if completion.choices else ""

        # Best-effort mode isn't schema-constrained, so keep the brace-extraction
        # fallback in case the model still wraps the JSON in prose or markdown fences.
        try:
            return json.loads(text)
        except ValueError:
            try:
                start = text.index('{')
                end = text.rindex('}') + 1
                return json.loads(text[start:end])
            except (ValueError, IndexError) as e:
                raise ValueError(f"Failed to parse LLM response as JSON: {e}")

    def analyze_with_grounding(self, analysis: dict, fen: str, human_move: Optional[str] = None) -> AnalyzeResponse:
        """
        Full pipeline: build prompt → call LLM → validate output → return response.
        """
        prompt = self.build_grounding_prompt(analysis, fen, human_move)
        llm_result = self.call_llm(prompt)

        # Validate that all cited squares/moves appear in the source analysis
        # This is the core technical differentiator
        validated_steps = self._validate_llm_output(llm_result, analysis)

        # Build explanation steps
        explanation_steps = [
            AnalysisStep(
                text=step["text"],
                highlight_squares=step["highlight_squares"],
                move_uci=step.get("move_uci"),
            )
            for step in validated_steps.get("steps", [])
        ]

        best_move = analysis.get("best_line", ["e2e4"])[0] if analysis.get("best_line") else "e2e4"
        best_eval = analysis.get("eval_cp", 0)

        # Build human move comparison only when we actually have a real human_eval —
        # a comparison with a defaulted-to-zero eval is misleading, not just incomplete.
        human_comparison = None
        human_eval = analysis.get("human_eval")
        if human_move and human_eval is not None:
            human_comparison = HumanMoveComparison(
                human_move=human_move,
                best_move=best_move,
                human_eval_cp=human_eval,
                best_eval_cp=best_eval,
                eval_swing_cp=best_eval - human_eval,
            )

        return AnalyzeResponse(
            best_move=best_move,
            eval_cp=best_eval,
            explanation_steps=explanation_steps,
            human_move_comparison=human_comparison,
            engine_source=analysis.get("engine_source", "stockfish"),
        )

    def _validate_llm_output(self, llm_result: dict, source_analysis: dict) -> dict:
        """
        Validate that every square and move cited in the LLM output actually
        appears in the Stockfish source analysis. Drop steps that violate this
        constraint — no partial credit, since a single unverifiable step
        undermines the "every claim traces to Stockfish" guarantee.

        Moves are checked via the structured 'move_uci' field the prompt requires,
        not by regex-scraping 'text' — the model was asked for prose, so scraping
        prose for a specific notation format is unreliable by construction.
        """
        validated_steps = []
        key_squares = set(source_analysis.get("key_squares", []))
        best_line = source_analysis.get("best_line", [])
        human_line = source_analysis.get("human_line", []) or []
        allowed_moves = set(best_line) | set(human_line)

        for step in llm_result.get("steps", []):
            highlighted = set(step.get("highlight_squares", []))
            if not highlighted.issubset(key_squares):
                continue  # cites squares not in the source analysis

            move_uci = step.get("move_uci")
            if move_uci is not None and move_uci not in allowed_moves:
                continue  # cites a move Stockfish never actually played

            validated_steps.append(step)

        return {"steps": validated_steps}