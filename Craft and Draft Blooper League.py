import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Streamlit Page Setup ---
st.set_page_config(page_title="Total Points Blooper League", layout="wide")

# Auto-refresh every 30 seconds
st_autorefresh(interval=30000, key="blooper_league_refresh")

LEAGUE_1_ID = 858
LEAGUE_2_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"


@st.cache_data(ttl=10)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_blooper_standings():
    """Calculates live total points by summing live match points across all gameweeks."""
    player_stats = []

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if not data or not isinstance(data, dict):
            continue

        entries = data.get("league_entries", [])
        matches = data.get("matches", [])

        # 1. Map entry IDs and initialize live points counter
        entry_map = {}
        live_points = {}

        for e in entries:
            if isinstance(e, dict):
                e_id = e.get("id")
                entry_map[e_id] = {
                    "player_name": f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip(),
                    "team_name": e.get("entry_name", "Team"),
                }
                live_points[e_id] = 0

        # 2. Sum live points from all started & finished matches
        for m in matches:
            if isinstance(m, dict) and (m.get("started") or m.get("finished")):
                e1 = m.get("league_entry_1")
                e2 = m.get("league_entry_2")
                pts1 = m.get("league_entry_1_points", 0)
                pts2 = m.get("league_entry_2_points", 0)

                if e1 in live_points:
                    live_points[e1] += pts1
                if e2 in live_points:
                    live_points[e2] += pts2

        # 3. Build player stat rows
        for e_id, info in entry_map.items():
            player_stats.append({
                "Player Name": info["player_name"],
                "Team Name": info["team_name"],
                "Total Points": live_points.get(e_id, 0),
            })

    # Fill placeholder spots up to 16 if leagues are not full
    if len(player_stats) < 16:
        for p in range(len(player_stats) + 1, 17):
            player_stats.append({
                "Player Name": f"Placeholder Player {p}",
                "Team Name": f"Placeholder Team {p}",
                "Total Points": 0,
            })

    df = pd.DataFrame(player_stats)
    if df.empty:
        return df

    # Sort from LOWEST points to HIGHEST points (Blooper style)
    df.sort_values(
        by=["Total Points", "Player Name"], ascending=[True, True], inplace=True
    )
    df.reset_index(drop=True, inplace=True)

    ranked_rows = []
    total_players = len(df)

    for idx, row in df.iterrows():
        rank_num = idx + 1
        if rank_num == 1:
            rank_str = "💩 1"
        elif rank_num == total_players:
            rank_str = f"⭐ {rank_num}"
        else:
            rank_str = str(rank_num)

        ranked_rows.append({
            "Rank": rank_str,
            "Player Name": row["Player Name"],
            "Team Name": row["Team Name"],
            "Total Points Scored": row["Total Points"],
        })

    return pd.DataFrame(ranked_rows)


# --- App Render ---
st.title("💩 Total Points Blooper League")
st.caption(
    "Live combined standings across both leagues — lowest point scorers rank highest!"
)

df_blooper = get_blooper_standings()

if not df_blooper.empty:
    st.dataframe(df_blooper, use_container_width=True, hide_index=True)
else:
    st.error("Connecting to Premier League servers... Please refresh if data does not load.")

if not df_blooper.empty:
    st.dataframe(df_blooper, use_container_width=True, hide_index=True)
else:
    st.error("Failed to load data from FPL Draft servers.")
