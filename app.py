import time
import json
from dataclasses import dataclass
from typing import Any

import requests
import streamlit as st

POLL_SECONDS = 15
MAX_STREAMERS = 10
GAMES_TO_ANALYZE = 1
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
    language: str
    blunders_last_game: int | None
    analyzed_games: int
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


def _extract_player_blunders(game: dict[str, Any], username: str) -> int | None:
    username_lc = username.lower()
    players = game.get("players", {})
    for color in ("white", "black"):
        player = players.get(color, {})
        user_name = (player.get("user") or {}).get("name", "")
        if user_name.lower() == username_lc:
            analysis = player.get("analysis", {})
            if isinstance(analysis, dict):
                if isinstance(analysis.get("blunder"), int):
                    return analysis["blunder"]
                if isinstance(analysis.get("blunders"), int):
                    return analysis["blunders"]

    analysis = game.get("analysis", {})
    if isinstance(analysis, dict):
        if isinstance(analysis.get("blunder"), int):
            return analysis["blunder"]
        if isinstance(analysis.get("blunders"), int):
            return analysis["blunders"]

        for color in ("white", "black"):
            color_stats = analysis.get(color, {})
            if isinstance(color_stats, dict):
                if isinstance(color_stats.get("blunder"), int):
                    return color_stats["blunder"]
                if isinstance(color_stats.get("blunders"), int):
                    return color_stats["blunders"]

    return None


def fetch_user_games(
    username: str, max_games: int = GAMES_TO_ANALYZE
) -> list[dict[str, Any]]:
    url = LICHESS_GAMES_URL_TEMPLATE.format(username=username)
    response = requests.get(
        url,
        params={"max": max_games, "analysis": "true", "pgnInJson": "true"},
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
    language = str(stream.get("lang") or "-")
    stream_url = str(stream.get("url") or "")
    popularity_score = _compute_popularity_score(streamer)

    blunders_last_game: int | None = None
    analyzed_games = 0
    games = fetch_user_games(username, max_games=GAMES_TO_ANALYZE)
    for game in games:
        blunders = _extract_player_blunders(game, username)
        if blunders is None:
            continue
        blunders_last_game = blunders
        analyzed_games += 1
        break

    return StreamerScore(
        username=username,
        display_name=display_name,
        stream_status=stream_status,
        language=language,
        blunders_last_game=blunders_last_game,
        analyzed_games=analyzed_games,
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
        scores.sort(
            key=lambda x: (
                x.popularity_score,
                x.blunders_last_game if x.blunders_last_game is not None else -1,
            ),
            reverse=True,
        )
        return scores, None
    except requests.RequestException as exc:
        return [], f"API request failed: {exc}"


def _render_table(scores: list[StreamerScore]) -> None:
    if not scores:
        st.info("No live streamers found or no analyzed games available.")
        return

    rows = []
    for s in scores:
        rows.append(
            {
                "Streamer": s.display_name,
                "Username": s.username,
                "Popularity score": s.popularity_score,
                "Blunders (latest game)": s.blunders_last_game
                if s.blunders_last_game is not None
                else "-",
                "Analyzed latest game": "Yes" if s.analyzed_games else "No",
                "Stream status": s.stream_status,
                "Language": s.language,
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
