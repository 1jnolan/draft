import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Streamlit Page Setup ---
st.set_page_config(page_title="Total Points Blooper League", layout="wide")
st_autorefresh(interval=10000, key="blooper_league_refresh")

LEAGUE_1_ID = 858
LEAGUE_2_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"


@st.cache_data(ttl=5)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_blooper_standings():
    """Fetches total points for all players across both leagues and formats the Blooper Table."""
    player_stats = []

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if not data:
            continue

        # Map entry IDs to Player Name and Team Name
        entries = data.get("league_entries", [])
        entry_map = {
            e["id"]: {
                "player_name": f"{e['player_first_name']} {e['player_last_name']}",
                "team_name": e["entry_name"]
            }
            for e in entries
        }

        # Extract standings / total points for each entry
        standings = data.get("standings", [])
        for s in standings:
            e_id = s.get("league_entry")
            if e_id in entry_map:
                player_stats.append({
                    "Player Name": entry_map[e_id]["player_name"],
                    "Team Name": entry_map[e_id]["team_name"],
                    "Total Points": s.get("points_for", 0)
                })

    # Fill missing spots with placeholders up to 16 if leagues aren't full yet
    if len(player_stats) < 16:
        for p in range(len(player_stats) + 1, 17):
            player_stats.append({
                "Player Name": f"Placeholder Player {p}",
                "Team Name": f"Placeholder Team {p}",
                "Total Points": 0
            })

    # Create DataFrame
    df = pd.DataFrame(player_stats)

    # Sort from LOWEST points to HIGHEST points
    df.sort_values(by=["Total Points", "Player Name"], ascending=[True, True], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Assign Ranks with Emoji Icons for 1st (lowest) and 16th (highest)
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
            "Total Points Scored": row["Total Points"]
        })

    return pd.DataFrame(ranked_rows)


# --- App Render ---
st.title("💩 Total Points Blooper League")
st.caption("Combined standings across both leagues — lowest point scorers rank highest!")

df_blooper = get_blooper_standings()

if not df_blooper.empty:
    st.dataframe(df_blooper, use_container_width=True, hide_index=True)
else:
    st.error("Failed to load data from FPL Draft servers.")
