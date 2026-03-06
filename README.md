# Lichess Streamer Blunder Dashboard

Live Streamlit dashboard that polls Lichess every 15 seconds, ranks up to 10 online streamers using a popularity proxy, and shows each streamer's results from their latest 10 games (latest first). It also shows a second table for top Lichess players (configured as top 10 blitz) with the same 10-game result view.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- Poll interval is fixed at 15 seconds (`POLL_SECONDS` in `app.py`).
- No retry logic is used: if a call fails, the app waits for the next 15-second poll.
- Streamers are loaded from `/api/streamer/live` with fallback to `/api/streamers`.
- Top players are loaded from `/api/player/top/{count}/{perfType}` (currently `count=10`, `perfType=blitz`).
- Per-user game fetches are executed concurrently with a bounded thread pool to keep refreshes responsive.
