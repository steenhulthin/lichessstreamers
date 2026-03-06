import time
import json
from dataclasses import dataclass
from typing import Any

import requests
import streamlit as st

POLL_SECONDS = 15
MAX_STREAMERS = 10
GAMES_TO_FETCH = 10
LICHESS_STREAMERS_URLS = [
    "https://lichess.org/api/streamer/live",
    "https://lichess.org/api/streamers",
]
LICHESS_GAMES_URL_TEMPLATE = "https://lichess.org/api/games/user/{username}"
REQUEST_TIMEOUT_SECONDS = 12


@dataclass
class StreamerScore:
    username: str
    display_name: str
    stream_status: str
    last_10_results: str
    popularity_score: int
    profile_url: str
    stream_url: str


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        url,
        params=params,
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def fetch_live_streamers() -> list[dict[str, Any]]:
    for url in LICHESS_STREAMERS_URLS:
        try:
            payload = _get_json(url)
        except requests.RequestException:
            continue
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("streamers"), list):
                return payload["streamers"]
            if isinstance(payload.get("data"), list):
                return payload["data"]
    return []


def _extract_player_color(game: dict[str, Any], username: str) -> str | None:
    username_lc = username.lower()
    players = game.get("players", {})
    for color in ("white", "black"):
        player = players.get(color, {})
        user_name = (player.get("user") or {}).get("name", "")
        if user_name.lower() == username_lc:
            return color

    return None


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
    lines = response.text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            if len(lines) == 1:
                parsed = response.json()
                if isinstance(parsed, list):
                    return [g for g in parsed if isinstance(g, dict)]
                if isinstance(parsed, dict):
                    return [parsed]
            games.append(json.loads(line))
        except ValueError:
            continue
    return games


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


def compute_streamer_score(streamer: dict[str, Any]) -> StreamerScore:
    username = str(streamer.get("id") or streamer.get("name") or "").strip()
    display_name = str(streamer.get("name") or username)
    stream = streamer.get("stream") or {}
    stream_status = str(stream.get("status") or "live")
    stream_url = str(stream.get("url") or "")
    popularity_score = _compute_popularity_score(streamer)

    games = fetch_user_games(username, max_games=GAMES_TO_FETCH)
    results = [_game_result_for_user(game, username) for game in games]
    last_10_results = " ".join(results) if results else "-"

    return StreamerScore(
        username=username,
        display_name=display_name,
        stream_status=stream_status,
        last_10_results=last_10_results,
        popularity_score=popularity_score,
        profile_url=f"https://lichess.org/@/{username}",
        stream_url=stream_url,
    )


def load_dashboard_data() -> tuple[list[StreamerScore], str | None]:
    try:
        streamers = fetch_live_streamers()
        streamers = sorted(
            streamers,
            key=_compute_popularity_score,
            reverse=True,
        )[:MAX_STREAMERS]
        scores: list[StreamerScore] = []
        for streamer in streamers:
            username = str(streamer.get("id") or streamer.get("name") or "").strip()
            if not username:
                continue
            try:
                scores.append(compute_streamer_score(streamer))
            except requests.RequestException:
                continue
        scores.sort(key=lambda x: x.popularity_score, reverse=True)
        return scores, None
    except requests.RequestException as exc:
        return [], f"API request failed: {exc}"


def _render_table(scores: list[StreamerScore]) -> None:
    if not scores:
        st.info("No live streamers found or no recent games available.")
        return

    rows = []
    for s in scores:
        rows.append(
            {
                "Streamer": s.display_name,
                "Username": s.username,
                "Popularity score": s.popularity_score,
                "Last 10 results": s.last_10_results,
                "Stream status": s.stream_status,
                "Profile": s.profile_url,
                "Stream": s.stream_url or "-",
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


st.set_page_config(page_title="Lichess Streamer Blunder Dashboard", layout="wide")
st.title("Lichess Streamer Blunder Dashboard")
st.caption(
    f"Polling Lichess API every {POLL_SECONDS} seconds. No retry on failure; next poll attempts again."
)


@st.fragment(run_every=POLL_SECONDS)
def live_dashboard() -> None:
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    scores, error = load_dashboard_data()
    st.write(f"Last refresh: {started}")
    if error:
        st.error(error)
        return
    _render_table(scores)


live_dashboard()
