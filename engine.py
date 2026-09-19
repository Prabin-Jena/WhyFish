import os
import shutil
import subprocess
from typing import Optional

import chess
import chess.engine


def _is_executable_stockfish(path: str) -> bool:
    try:
        result = subprocess.run(
            [path, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
        return False


def resolve_stockfish_path(custom_path: Optional[str] = None) -> str:
    """
    Locates the Stockfish executable by checking candidate locations in order:
      1. Explicit custom_path argument (if provided)
      2. STOCKFISH_PATH environment variable (if set)
      3. /usr/local/bin/stockfish (explicit Linux/Render symlink or binary)
      4. /usr/games/stockfish (explicit Linux Debian/Ubuntu package location)
      5. 'stockfish' or 'stockfish.exe' found via system PATH
      6. Fallback string 'stockfish'
    """
    candidates = []

    if custom_path:
        candidates.append(custom_path)

    env_path = os.environ.get("STOCKFISH_PATH", "").strip()
    if env_path:
        candidates.append(env_path)

    # Explicit paths first (crucial for Linux/Docker/Render where PATH might not contain /usr/games)
    candidates.extend([
        "/usr/local/bin/stockfish",
        "/usr/games/stockfish",
    ])

    # System PATH lookups (Windows / local development / custom installs)
    which_stockfish = shutil.which("stockfish")
    if which_stockfish:
        candidates.append(which_stockfish)

    which_exe = shutil.which("stockfish.exe")
    if which_exe and which_exe not in candidates:
        candidates.append(which_exe)

    candidates.append("stockfish")

    for candidate in candidates:
        if not candidate:
            continue
        # If candidate contains directory separators or is absolute
        if os.path.isabs(candidate) or os.path.sep in candidate or (os.path.altsep and os.path.altsep in candidate):
            if os.path.isfile(candidate) and _is_executable_stockfish(candidate):
                return candidate
        else:
            resolved = shutil.which(candidate)
            if resolved and os.path.isfile(resolved) and _is_executable_stockfish(resolved):
                return resolved
            if _is_executable_stockfish(candidate):
                return candidate

    return custom_path or env_path or "/usr/local/bin/stockfish"


class EngineAnalysis:

    def __init__(self, stockfish_path: Optional[str] = None):
        self._custom_stockfish_path = stockfish_path
        self.stockfish_path = resolve_stockfish_path(stockfish_path)
        self.engine = None
        self._stockfish_available = None

    # ------------------------------------------------------------------
    # Stockfish availability
    # ------------------------------------------------------------------

    def _check_stockfish(self) -> bool:

        if self._stockfish_available is not None:
            return self._stockfish_available

        if not self.stockfish_path or not _is_executable_stockfish(self.stockfish_path):
            self.stockfish_path = resolve_stockfish_path(self._custom_stockfish_path)

        self._stockfish_available = _is_executable_stockfish(self.stockfish_path)
        return self._stockfish_available

    # ------------------------------------------------------------------
    # Engine lifecycle
    # ------------------------------------------------------------------

    def start_engine(self):

        if self.engine is not None:
            return

        if not self._check_stockfish():
            raise RuntimeError(
                "Stockfish binary not found. "
                "Make sure 'stockfish' is available on PATH."
            )

        try:
            self.engine = (
                chess.engine.SimpleEngine.popen_uci(
                    self.stockfish_path
                )
            )

        except Exception as exc:
            self.engine = None

            raise RuntimeError(
                f"Could not start Stockfish: {exc}"
            ) from exc

    def stop_engine(self):

        if self.engine is None:
            return

        try:
            self.engine.quit()
        except Exception:
            pass
        finally:
            self.engine = None

    def _analyse_with_restart(
        self,
        board: chess.Board,
        depth: int,
        multipv: int,
    ):
        """
        Run Stockfish analysis and automatically restart the engine
        once if the underlying Stockfish process has died.
        """

        self.start_engine()

        try:
            return self.engine.analyse(
                board,
                chess.engine.Limit(
                    depth=depth
                ),
                multipv=multipv,
            )

        except chess.engine.EngineTerminatedError:
            # Stockfish process died. Clear the stale engine instance
            # and start a fresh process before retrying once.
            self.stop_engine()
            self.start_engine()

            return self.engine.analyse(
                board,
                chess.engine.Limit(
                    depth=depth
                ),
                multipv=multipv,
            )
    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze_position(
        self,
        fen: str,
        human_move: Optional[str] = None,
        multipv: int = 3,
        depth: int = 18,
    ) -> dict:

        board = chess.Board(fen)

        self.start_engine()

        if self.engine is None:
            raise RuntimeError(
                "Stockfish engine is not running."
            )

        # --------------------------------------------------------------
        # Main position
        # --------------------------------------------------------------

        analysis = self._analyse_with_restart(
            board,
            depth,
            multipv,
        )

        if not analysis:
            raise RuntimeError(
                "Stockfish returned no analysis."
            )

        best_line_info = analysis[0]

        best_line = [
            str(move)
            for move in best_line_info.get(
                "pv",
                [],
            )
        ]

        score = best_line_info.get("score")

        if score is None:
            raise RuntimeError(
                "Stockfish returned no evaluation."
            )

        eval_cp = score.relative.score(
            mate_score=100000
        )

        if eval_cp is None:
            eval_cp = 0

        # --------------------------------------------------------------
        # Human move
        # --------------------------------------------------------------

        human_line = None
        human_eval_cp = None

        if human_move:

            try:
                human_move_obj = chess.Move.from_uci(
                    human_move
                )
            except ValueError as exc:
                raise ValueError(
                    "Human move must be valid UCI notation."
                ) from exc

            if human_move_obj not in board.legal_moves:
                raise ValueError(
                    f"Illegal human move: {human_move}"
                )

            board.push(human_move_obj)

            try:

                human_analysis = self._analyse_with_restart(
                    board,
                    depth,
                    1,
                )

                if not human_analysis:
                    raise RuntimeError(
                        "Stockfish returned no analysis "
                        "for the human move."
                    )

                human_info = human_analysis[0]

                human_line = [
                    str(move)
                    for move in human_info.get(
                        "pv",
                        [],
                    )
                ]

                human_score = human_info.get(
                    "score"
                )

                if human_score is not None:

                    opponent_eval = (
                        human_score.relative.score(
                            mate_score=100000
                        )
                    )

                    human_eval_cp = -(
                        opponent_eval or 0
                    )

            finally:
                board.pop()

        # --------------------------------------------------------------
        # Key squares
        # --------------------------------------------------------------

        key_squares = set()

        temp_board = chess.Board(fen)

        for move_uci in best_line[:3]:

            try:

                move = chess.Move.from_uci(
                    move_uci
                )

                key_squares.add(
                    chess.square_name(
                        move.from_square
                    )
                )

                key_squares.add(
                    chess.square_name(
                        move.to_square
                    )
                )

                temp_board.push(move)

            except (
                ValueError,
                chess.IllegalMoveError,
            ):
                break

        return {
            "best_line": best_line,
            "eval_cp": eval_cp,
            "human_line": human_line,
            "human_eval": human_eval_cp,
            "key_squares": sorted(
                key_squares
            ),
            "engine_source": "stockfish",
        }


engine_analysis = EngineAnalysis()