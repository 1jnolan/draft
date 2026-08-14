import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Standings & Current GW", layout="wide")
st_autorefresh(interval=5000, key="fpl_refresh_app1")

LEAGUE_ID = 4159
URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
HEADERS = {"User-Agent": "Mozilla/5.0"}

@st.cache_data(ttl=3)
def fetch_league_data():
    try:
        res = requests.get(URL, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None

data = fetch_league_data()

if data:
    entries = data.get("league_entries", [])
    entry_map = {
        e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
        for e in entries
    }

    # 1. League Standings
    st.subheader("🏆 Current League Standings")
    standings_raw = data.get("standings", [])
    standings_list = [{
        "Rank": s.get("rank"),
        "Manager / Team Name": entry_map.get(s.get("league_entry")),
        "Played": s.get("matches_played", 0),
        "Won": s.get("matches_won", 0),
        "Drawn": s.get("matches_drawn", 0),
        "Lost": s.get("matches_lost", 0),
        "Points For": s.get("points_for", 0),
        "Total Points": s.get("total", 0),
    } for s in standings_raw]
    
    df_standings = pd.DataFrame(standings_list)
    if not df_standings.empty:
        df_standings.sort_values(by="Rank", inplace=True)
        st.dataframe(df_standings, use_container_width=True, hide_index=True)

    st.divider()

    # 2. Current Gameweek Fixtures
    st.subheader("⚡ Current Gameweek Fixtures & Scores")
    matches_raw = data.get("matches", [])
    
    # Identify the highest started/finished event or current GW
    events = [m.get("event") for m in matches_raw if m.get("event")]
    current_gw = max(events) if events else 1

    current_fixtures = [{
        "Home Team": entry_map.get(m.get("league_entry_1")),
        "Home Score": m.get("league_entry_1_points", 0),
        "Away Score": m.get("league_entry_2_points", 0),
        "Away Team": entry_map.get(m.get("league_entry_2")),
        "Status": "Finished" if m.get("finished") else ("Live" if m.get("started") else "Scheduled")
    } for m in matches_raw if m.get("event") == current_gw]

    df_current = pd.DataFrame(current_fixtures)
    if not df_current.empty:
        st.caption(f"Showing live updates for **Gameweek {current_gw}**")
        st.dataframe(df_current, use_container_width=True, hide_index=True)
else:
    st.error("Failed to load league standings and fixtures.")
