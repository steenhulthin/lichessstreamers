# Lichess Streamers and Top Players Dashboard

Live Streamlit dashboard that polls Lichess every 10 seconds, ranks up to 15 online streamers using a popularity proxy, and shows each streamer's results from their latest 10 games (latest last). It also shows a second table for top Lichess players (configured as top 25 blitz) with the same 10-game result view, plus a puzzle panel from `/api/puzzle/daily` with a FEN board.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- Polling Lichess API every 10 seconds. Shows warnings for failed requests (including HTTP 429).
- Poll interval is fixed at 10 seconds (`POLL_SECONDS` in `app.py`).
- No retry logic is used: if a call fails, the app waits for the next 10-second poll.
- Streamers are loaded from `/api/streamer/live` with fallback to `/api/streamers`.
- Top players are loaded from `/api/player/top/{count}/{perfType}` (currently `count=25`, `perfType=blitz`).
- Puzzle data is loaded from `/api/puzzle/daily` (fallback `/api/puzzle/next`).
- Puzzle FEN is derived from `game.pgn` and `puzzle.initialPly` (the daily puzzle payload does not reliably include a direct `fen` field).
- Per-user game fetches are cached to reduce request volume (`st.cache_data` TTL in `app.py`).
- API failures are surfaced as warnings in the UI, including explicit HTTP 429 rate-limit warnings.
