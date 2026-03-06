import json
import io
import time
from dataclasses import dataclass
from typing import Any

import requests
import streamlit as st

try:
    import chess.pgn as chess_pgn
except ImportError:
    chess_pgn = None

POLL_SECONDS = 10
MAX_STREAMERS = 10
GAMES_TO_FETCH = 10
TOP_PLAYERS_COUNT = 10
TOP_PLAYERS_PERF_TYPE = "blitz"
RESULTS_ORDER_LABEL = "latest last"
LIVE_STREAMERS_CACHE_TTL_SECONDS = 10
TOP_PLAYERS_CACHE_TTL_SECONDS = 60
USER_GAMES_CACHE_TTL_SECONDS = 120
PUZZLE_CACHE_TTL_SECONDS = 60
PLACEHOLDER_PUZZLE_FEN = "rnbq1rk1/ppp1bpQ1/3p1np1/4p3/2B5/2B2N2/PPPPPPP1/RNB3KR w - - 0 1"
PLACEHOLDER_PUZZLE_HINT = "Placeholder mate in one: Qh8#"
LICHESS_STREAMERS_URLS = [
    "https://lichess.org/api/streamer/live",
    "https://lichess.org/api/streamers",
]
LICHESS_GAMES_URL_TEMPLATE = "https://lichess.org/api/games/user/{username}"
LICHESS_TOP_PLAYERS_URL_TEMPLATE = "https://lichess.org/api/player/top/{count}/{perf_type}"
LICHESS_PUZZLE_URLS = [
    "https://lichess.org/api/puzzle/daily",
    "https://lichess.org/api/puzzle/next",
]
REQUEST_TIMEOUT_SECONDS = 12


@dataclass
class StreamerScore:
    display_name: str
    stream_status: str
    last_10_results: str
    streak: str
    popularity_score: int
    profile_url: str


@dataclass
class TopPlayerScore:
    display_name: str
    title: str
    rating: int | None
    last_10_results: str
    streak: str
    profile_url: str


@dataclass
class PuzzleInfo:
    puzzle_id: str
    rating: int | None
    themes: list[str]
    fen: str
    puzzle_url: str


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        url,
        params=params,
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=LIVE_STREAMERS_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_live_streamers() -> list[dict[str, Any]]:
    for url in LICHESS_STREAMERS_URLS:
        try:
            payload = _get_json(url)
        except requests.RequestException:
            continue
        if isinstance(payload, list):
            return [s for s in payload if isinstance(s, dict)]
        if isinstance(payload, dict):
            if isinstance(payload.get("streamers"), list):
                return [s for s in payload["streamers"] if isinstance(s, dict)]
            if isinstance(payload.get("data"), list):
                return [s for s in payload["data"] if isinstance(s, dict)]
    return []


@st.cache_data(ttl=TOP_PLAYERS_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_top_players(
    count: int = TOP_PLAYERS_COUNT, perf_type: str = TOP_PLAYERS_PERF_TYPE
) -> list[dict[str, Any]]:
    url = LICHESS_TOP_PLAYERS_URL_TEMPLATE.format(count=count, perf_type=perf_type)
    payload = _get_json(url)
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("users"), list):
        return [p for p in payload["users"] if isinstance(p, dict)]
    return []


@st.cache_data(ttl=USER_GAMES_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_user_games(
    username: str, max_games: int = GAMES_TO_FETCH
) -> list[dict[str, Any]]:
    url = LICHESS_GAMES_URL_TEMPLATE.format(username=username)
    response = requests.get(
        url,
        params={"max": max_games, "pgnInJson": "true"},
        headers={"Accept": "application/x-ndjson"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    games: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            games.append(parsed)
    return games


@st.cache_data(ttl=PUZZLE_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_puzzle_payload() -> dict[str, Any]:
    for url in LICHESS_PUZZLE_URLS:
        try:
            payload = _get_json(url)
        except requests.RequestException:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _extract_player_color(game: dict[str, Any], username: str) -> str | None:
    username_lc = username.lower()
    players = game.get("players", {})
    for color in ("white", "black"):
        player = players.get(color, {})
        user_name = (player.get("user") or {}).get("name", "")
        if user_name.lower() == username_lc:
            return color
    return None


def _game_timestamp(game: dict[str, Any]) -> int:
    for field in ("lastMoveAt", "createdAt"):
        value = game.get(field)
        if isinstance(value, int):
            return value
    return -1


def _order_games_latest_last(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(games, key=_game_timestamp)


def _game_result_for_user(game: dict[str, Any], username: str) -> str:
    color = _extract_player_color(game, username)
    if color is None:
        return "-"

    winner = str(game.get("winner") or "").lower()
    if winner in ("white", "black"):
        return "W" if winner == color else "L"

    status = str(game.get("status") or "").lower()
    if status in {"aborted", "nostart", "created", "started", "unknownfinish"}:
        return "-"
    return "D"


def _compute_streak(results: list[str]) -> str:
    if len(results) < 5:
        return "-"

    recent_five = results[-5:]
    if all(result == "W" for result in recent_five):
        return "\U0001F525 Win x5"
    if all(result == "D" for result in recent_five):
        return "\U0001F91D Draw x5"
    if all(result == "L" for result in recent_five):
        return "\U0001F480 Loss x5"
    return "-"


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def _compute_popularity_score(streamer: dict[str, Any]) -> int:
    stream = streamer.get("stream") or {}
    top_level_viewers = _to_int(streamer.get("viewers")) or 0
    nested_viewers = _to_int(stream.get("viewers")) or 0
    viewer_count = max(top_level_viewers, nested_viewers)

    follower_count = max(
        _to_int(streamer.get("nbFollowers")) or 0,
        _to_int(streamer.get("followers")) or 0,
        _to_int(stream.get("followers")) or 0,
    )

    has_title = int(bool(streamer.get("title")))
    is_patron = int(bool(streamer.get("patron")))
    has_stream_link = int(bool(stream.get("url")))

    return (
        viewer_count * 1000
        + follower_count * 10
        + has_title * 500
        + is_patron * 250
        + has_stream_link * 100
    )


def _extract_perf_rating(player: dict[str, Any], perf_type: str) -> int | None:
    perfs = player.get("perfs", {})
    if isinstance(perfs, dict):
        perf_data = perfs.get(perf_type, {})
        if isinstance(perf_data, dict) and isinstance(perf_data.get("rating"), int):
            return perf_data["rating"]
    if isinstance(player.get("rating"), int):
        return player["rating"]
    return None


def _extract_status_code(exc: requests.RequestException) -> int | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _derive_fen_from_pgn(pgn: str, initial_ply: int | None) -> str:
    if chess_pgn is None:
        return ""
    if not pgn:
        return ""
    try:
        game = chess_pgn.read_game(io.StringIO(pgn))
    except Exception:
        return ""
    if game is None:
        return ""

    board = game.board()
    ply_target = initial_ply if isinstance(initial_ply, int) and initial_ply >= 0 else 0
    for idx, move in enumerate(game.mainline_moves()):
        if idx >= ply_target:
            break
        board.push(move)
    return board.fen()


def _extract_puzzle_info(payload: dict[str, Any]) -> PuzzleInfo:
    puzzle = payload.get("puzzle", {})
    game = payload.get("game", {})

    puzzle_id = str((puzzle or {}).get("id") or "")
    rating = (puzzle or {}).get("rating")
    rating_int = rating if isinstance(rating, int) else None
    initial_ply = (puzzle or {}).get("initialPly")
    initial_ply_int = initial_ply if isinstance(initial_ply, int) else None
    pgn = str((game or {}).get("pgn") or "")
    themes = (puzzle or {}).get("themes")
    theme_list = [str(t) for t in themes] if isinstance(themes, list) else []
    derived_fen = _derive_fen_from_pgn(pgn, initial_ply_int)
    fen = str(
        (puzzle or {}).get("fen")
        or (game or {}).get("fen")
        or payload.get("fen")
        or derived_fen
        or ""
    ).strip()
    puzzle_url = f"https://lichess.org/training/{puzzle_id}" if puzzle_id else "https://lichess.org/training"

    return PuzzleInfo(
        puzzle_id=puzzle_id,
        rating=rating_int,
        themes=theme_list,
        fen=fen,
        puzzle_url=puzzle_url,
    )


def _fen_to_board_rows(fen: str) -> list[list[str]] | None:
    piece_map = {
        "K": "\u2654",
        "Q": "\u2655",
        "R": "\u2656",
        "B": "\u2657",
        "N": "\u2658",
        "P": "\u2659",
        "k": "\u265A",
        "q": "\u265B",
        "r": "\u265C",
        "b": "\u265D",
        "n": "\u265E",
        "p": "\u265F",
    }

    parts = fen.strip().split()
    if not parts:
        return None
    ranks = parts[0].split("/")
    if len(ranks) != 8:
        return None

    board_rows: list[list[str]] = []
    for rank in ranks:
        row: list[str] = []
        for token in rank:
            if token.isdigit():
                row.extend([""] * int(token))
            elif token in piece_map:
                row.append(piece_map[token])
            else:
                return None
        if len(row) != 8:
            return None
        board_rows.append(row)
    return board_rows


def _render_fen_board(fen: str) -> None:
    board_rows = _fen_to_board_rows(fen)
    if board_rows is None:
        st.info("FEN is missing or invalid for this puzzle payload.")
        return

    html_rows: list[str] = []
    for rank_idx, row in enumerate(board_rows):
        cell_html: list[str] = []
        for file_idx, piece in enumerate(row):
            is_light = (rank_idx + file_idx) % 2 == 0
            bg = "#e2d6c2" if is_light else "#63b56a"
            piece_text = piece or "&nbsp;"
            cell_html.append(
                "<td style='width:20px;height:20px;text-align:center;vertical-align:middle;"
                f"font-size:30px;background:{bg};'>{piece_text}</td>"
            )
        html_rows.append(f"<tr>{''.join(cell_html)}</tr>")

    st.markdown(
        (
            "<table style='border-collapse:collapse;border:1px solid #666;'>"
            f"{''.join(html_rows)}"
            "</table>"
        ),
        unsafe_allow_html=True,
    )


def _render_puzzle_panel() -> None:
    st.subheader("Today's Puzzle")
    panel = st.empty()
    with panel.container():
        left_col, right_col = st.columns([1, 1])
        with left_col:
            st.caption("FEN Board")
            _render_fen_board(PLACEHOLDER_PUZZLE_FEN)
        with right_col:
            st.write("Puzzle ID: `placeholder`")
            st.write("Rating: `-`")
            st.write("Themes: `mate`")
            st.write(PLACEHOLDER_PUZZLE_HINT)
            st.code(PLACEHOLDER_PUZZLE_FEN, language="text")

    try:
        payload = fetch_puzzle_payload()
    except requests.RequestException as exc:
        st.warning(f"Puzzle request failed: {exc}")
        return

    puzzle = _extract_puzzle_info(payload)
    if not puzzle.fen and chess_pgn is None:
        st.warning(
            "Install dependency `chess` to derive FEN from PGN: `pip install -r requirements.txt`."
        )

    with panel.container():
        left_col, right_col = st.columns([1, 1])
        with left_col:
            st.caption("FEN Board")
            _render_fen_board(puzzle.fen)
        with right_col:
            st.write(f"Puzzle ID: `{puzzle.puzzle_id or '-'}`")
            st.write(f"Rating: `{puzzle.rating if puzzle.rating is not None else '-'}`")
            st.write(f"Themes: `{', '.join(puzzle.themes) if puzzle.themes else '-'}`")
            st.write(f"[Open on Lichess]({puzzle.puzzle_url})")
            st.code(puzzle.fen or "-", language="text")


def compute_streamer_score(streamer: dict[str, Any]) -> StreamerScore:
    username = str(streamer.get("id") or streamer.get("name") or "").strip()
    display_name = str(streamer.get("name") or username)
    stream = streamer.get("stream") or {}
    stream_status = str(stream.get("status") or "live")
    popularity_score = _compute_popularity_score(streamer)

    games = _order_games_latest_last(fetch_user_games(username, max_games=GAMES_TO_FETCH))
    results = [_game_result_for_user(game, username) for game in games]
    last_10_results = " ".join(results) if results else "-"
    streak = _compute_streak(results)

    return StreamerScore(
        display_name=display_name,
        stream_status=stream_status,
        last_10_results=last_10_results,
        streak=streak,
        popularity_score=popularity_score,
        profile_url=f"https://lichess.org/@/{username}",
    )


def compute_top_player_score(
    player: dict[str, Any], perf_type: str = TOP_PLAYERS_PERF_TYPE
) -> TopPlayerScore | None:
    username = str(player.get("id") or player.get("username") or "").strip()
    if not username:
        return None

    display_name = str(player.get("username") or player.get("name") or username)
    title = str(player.get("title") or "")
    rating = _extract_perf_rating(player, perf_type)

    games = _order_games_latest_last(fetch_user_games(username, max_games=GAMES_TO_FETCH))
    results = [_game_result_for_user(game, username) for game in games]
    last_10_results = " ".join(results) if results else "-"
    streak = _compute_streak(results)

    return TopPlayerScore(
        display_name=display_name,
        title=title,
        rating=rating,
        last_10_results=last_10_results,
        streak=streak,
        profile_url=f"https://lichess.org/@/{username}",
    )


def load_dashboard_data() -> tuple[list[StreamerScore], str | None]:
    try:
        streamers = fetch_live_streamers()
    except requests.RequestException as exc:
        return [], f"API request failed for live streamers: {exc}"

    streamers = sorted(
        streamers,
        key=_compute_popularity_score,
        reverse=True,
    )[:MAX_STREAMERS]

    scores: list[StreamerScore] = []
    failed_requests = 0
    rate_limited_requests = 0
    for streamer in streamers:
        username = str(streamer.get("id") or streamer.get("name") or "").strip()
        if not username:
            continue
        try:
            scores.append(compute_streamer_score(streamer))
        except requests.RequestException as exc:
            failed_requests += 1
            if _extract_status_code(exc) == 429:
                rate_limited_requests += 1

    scores.sort(key=lambda x: x.popularity_score, reverse=True)
    if failed_requests == 0:
        return scores, None
    if rate_limited_requests > 0:
        return (
            scores,
            f"{failed_requests} streamer game requests failed; {rate_limited_requests} hit HTTP 429 rate limit.",
        )
    return scores, f"{failed_requests} streamer game requests failed."


def load_top_players_data() -> tuple[list[TopPlayerScore], str | None]:
    try:
        top_players = fetch_top_players(
            count=TOP_PLAYERS_COUNT,
            perf_type=TOP_PLAYERS_PERF_TYPE,
        )
    except requests.RequestException as exc:
        return [], f"Top players API request failed: {exc}"

    scores: list[TopPlayerScore] = []
    failed_requests = 0
    rate_limited_requests = 0
    for player in top_players:
        try:
            score = compute_top_player_score(player, perf_type=TOP_PLAYERS_PERF_TYPE)
        except requests.RequestException as exc:
            failed_requests += 1
            if _extract_status_code(exc) == 429:
                rate_limited_requests += 1
            continue
        if score is None:
            continue
        scores.append(score)

    if failed_requests == 0:
        return scores, None
    if rate_limited_requests > 0:
        return (
            scores,
            f"{failed_requests} top-player game requests failed; {rate_limited_requests} hit HTTP 429 rate limit.",
        )
    return scores, f"{failed_requests} top-player game requests failed."


def _render_streamers_table(scores: list[StreamerScore]) -> None:
    if not scores:
        st.info("No live streamers found or no recent games available.")
        return

    rows = []
    for s in scores:
        rows.append(
            {
                "Streamer": s.display_name,
                "Popularity score": s.popularity_score,
                f"Last 10 results ({RESULTS_ORDER_LABEL})": s.last_10_results,
                "Streak": s.streak,
                "Stream status": s.stream_status,
                "Profile": s.profile_url,
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_top_players_table(scores: list[TopPlayerScore]) -> None:
    if not scores:
        st.info("No top players found or no recent games available.")
        return

    rows = []
    for s in scores:
        rows.append(
            {
                "Player": f"{s.title} {s.display_name}".strip(),
                f"{TOP_PLAYERS_PERF_TYPE.capitalize()} rating": (
                    s.rating if s.rating is not None else "-"
                ),
                f"Last 10 results ({RESULTS_ORDER_LABEL})": s.last_10_results,
                "Streak": s.streak,
                "Profile": s.profile_url,
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


st.set_page_config(page_title="Lichess Streamers and Top Players Dashboard", layout="wide")
st.title("Lichess Streamers and Top Players Dashboard")


@st.fragment(run_every=POLL_SECONDS)
def live_dashboard() -> None:
    st.write(f"Last refresh: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    _render_puzzle_panel()

    st.subheader("Live Streamers")
    streamers_slot = st.empty()
    streamers_slot.info("Loading live streamers...")
    streamer_scores, streamer_note = load_dashboard_data()
    with streamers_slot.container():
        if streamer_note:
            st.warning(streamer_note)
        _render_streamers_table(streamer_scores)

    st.subheader(f"Top {TOP_PLAYERS_PERF_TYPE.capitalize()} Players")
    top_slot = st.empty()
    top_slot.info("Loading top players...")
    top_scores, top_note = load_top_players_data()
    with top_slot.container():
        if top_note:
            st.warning(top_note)
        _render_top_players_table(top_scores)


live_dashboard()
