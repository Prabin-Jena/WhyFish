from pydantic import BaseModel
from typing import List, Optional

class AnalyzeRequest(BaseModel):
    fen: str
    human_move: Optional[str] = None

class AnalysisStep(BaseModel):
    text: str
    highlight_squares: List[str]
    move_uci: Optional[str] = None  # structured move citation, validated against best_line

class HumanMoveComparison(BaseModel):
    human_move: str
    best_move: str
    human_eval_cp: int
    best_eval_cp: int
    eval_swing_cp: int  # best_eval_cp - human_eval_cp, always well-defined

class AnalyzeResponse(BaseModel):
    best_move: str
    eval_cp: int
    explanation_steps: List[AnalysisStep]
    human_move_comparison: Optional[HumanMoveComparison] = None
    engine_source: str = "stockfish"  # "stockfish" or "mock" — never silently hidden from caller