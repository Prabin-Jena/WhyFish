# Whyfish — Product Requirements Document

**Tagline:** Stockfish knows what. Whyfish explains why.

**Event:** HackDevengers 2.0 (24hr virtual, open innovation, solo build)
**Build window:** Sept 19, 10:00 AM – Sept 20, 10:00 AM

---

## 1. Problem Statement

Chess engines like Stockfish output the objectively best move and a numeric
evaluation, but give no causal explanation a human can use to actually learn.
A player who sees `Kg7` recommended in a sharp position has no way to know
*why* it's correct versus their own intuitive move — the engine's reasoning
is buried in raw variations (principal variations, or "PVs") that are
unreadable to non-experts.

This is a documented, current gap: players explicitly ask engines/tools for
a "why," not just a "what" (Sept 2026 community discussion). Existing tools
(Chess.com analysis, Lichess) show eval bars and best-move arrows, not
causal, natural-language explanations grounded in the engine's actual
calculated lines.

## 2. Product Vision

Whyfish takes a chess position, runs Stockfish's real multi-line analysis,
and uses an LLM — constrained to only reference moves and threats that
actually appear in Stockfish's calculated variations — to generate a causal,
human-readable explanation of why the best move wins and why the human's
candidate move loses.

**Core differentiator:** the explanation is *grounded*. The LLM is not
asked "explain this chess position" from its own training knowledge (which
invites hallucinated tactics); it is given Stockfish's actual line-by-line
calculations as required source material and instructed to cite only
those lines. This is the same grounding/hallucination-mitigation pattern
used in production RAG systems, applied to a domain (chess) where
correctness is mechanically verifiable — which makes it a strong,
defensible portfolio piece for AI application engineering roles.

## 3. Target User (for the demo)

Not a specific persona to build a business around — the user, for hackathon
purposes, is **the judge**: someone who plays some chess, has seen an eval
bar before, and will immediately understand "the engine says this move is
better, and now I know why" without any onboarding.

## 4. Core User Flow

1. User loads a position — via FEN paste, interactive board setup, or a
   preset "interesting position" (recommended default for demo speed).
2. User optionally plays/selects their own candidate move.
3. User hits **Analyze**.
4. Backend runs Stockfish multi-PV analysis on the position.
5. Backend sends Stockfish's structured output (best line, eval, and — if
   the user provided one — the human move's line) to the LLM with a
   grounding-constrained prompt.
6. Frontend reveals the explanation in a staggered sequence: threat →
   response → why it matters → resulting evaluation, with the relevant
   board squares highlighting in sync.
7. (Stretch) Side-by-side comparison: "if you play the engine's move" vs
   "if you play your move," each with its own short causal explanation.

## 5. Scope

### In scope (MVP — must work for the demo)
- FEN input + a small set (5-8) of curated preset positions with genuine
  tactical/positional "why" stories (hand-picked and pre-tested before the
  hackathon if possible — this is the single highest-leverage prep task)
- Stockfish multi-PV analysis via `python-chess` + local binary
- One grounded LLM call producing a structured explanation
- Staggered-reveal animation with square highlighting
- 3-page vanilla HTML/CSS/JS frontend (input → analysis → about)

### Stretch (only if MVP is done with hours to spare)
- User-vs-engine move comparison view
- Basic eval bar with animated fill
- Ability to click through the actual PV move-by-move on the board

### Explicitly out of scope
- User accounts, saved history, or any persistence beyond `sessionStorage`
- Support for arbitrary time controls / live game analysis
- Mobile app packaging
- Any training of a custom model — Stockfish is the only "model," used as-is

## 6. Success Criteria (for the hackathon submission)
- A judge can go from "sees the page" to "understands the why" in under
  60 seconds with zero explanation from you
- The explanation is demonstrably grounded — every structured move and board-square reference in the explanation
must trace to Stockfish-generated evidence, while the natural-language
explanation is constrained by that evidence.
- Deployed, working link + clean GitHub repo with a README explaining the
  grounding mechanism specifically (this is the portfolio-relevant part)

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM ignores grounding constraint and hallucinates anyway | Strict system prompt + output schema requiring move citations; validate cited moves actually appear in the PV before rendering |
| Stockfish binary fails to run on deploy host | Test deployment target *before* hackathon day; have a Docker-based fallback with Stockfish pre-installed |
| Demo position doesn't produce an interesting "why" | Pre-select and pre-test 5-8 positions in advance — do not rely on live/random input for the primary demo |
| Running out of time on frontend polish | Vanilla JS + CSS only, no build step, no framework — see Architecture doc |

## 8. Post-Hackathon Value

Independent of the competition outcome, this becomes a standing portfolio
artifact: a small, complete, correctly-engineered example of constrained/
grounded LLM output applied to a verifiable domain — directly relevant
evidence for AI application development and AI/ML engineering roles.
