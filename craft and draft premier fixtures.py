import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Full Season Fixtures", layout="wide")
st_autorefresh(interval=30000, key="fpl_refresh_app2")

LEAGUE_ID = 858
URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
HEADERS = {"User-Agent": "Mozilla/5.0"}

@st.cache_data(ttl=10)
def fetch_data():
    try:
        res = requests.get(URL, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None

data = fetch_data()

if data and isinstance(data, dict):
    st.subheader("📅 Season Fixtures & Scores")
    
    entries = data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries if isinstance(e, dict)
    }

    matches_raw = data.get("matches", [])
    
    # 1. Detect Current / Active Gameweek
    live_gws = [m.get("event") for m in matches_raw if m.get("started") and not m.get("finished")]
    finished_gws = [m.get("event") for m in matches_raw if m.get("finished")]
    
    if live_gws:
        current_gw = max(live_gws)
    elif finished_gws:
        current_gw = min(max(finished_gws) + 1, 38)
    else:
        current_gw = 1

    # 2. Build Fixtures List (Mask scores for unplayed games)
    fixtures_list = []
    for m in matches_raw:
        if not isinstance(m, dict):
            continue
            
        gw = m.get("event")
        is_started = m.get("started", False)
        is_finished = m.get("finished", False)
        
        status = "Finished" if is_finished else ("Live" if is_started else "Scheduled")
        h_score = m.get("league_entry_1_points", 0) if (is_started or is_finished) else "-"
        a_score = m.get("league_entry_2_points", 0) if (is_started or is_finished) else "-"

        fixtures_list.append({
            "GW": gw,
            "Home Team": entry_map.get(m.get("league_entry_1"), f"Entry {m.get('league_entry_1')}"),
            "Home Score": h_score,
            "Away Score": a_score,
            "Away Team": entry_map.get(m.get("league_entry_2"), f"Entry {m.get('league_entry_2')}"),
            "Status": status
        })

    df_fixtures = pd.DataFrame(fixtures_list)

    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)
        
        # 3. Filter Options with Current Gameweek Default
        unique_gws = sorted([gw for gw in df_fixtures["GW"].dropna().unique()])
        all_options = ["All Gameweeks"] + [f"Gameweek {gw}" for gw in unique_gws]
        
        # Calculate default index for the current gameweek
        default_label = f"Gameweek {current_gw}"
        default_index = all_options.index(default_label) if default_label in all_options else 0

        selected_option = st.selectbox(
            "Select Gameweek to View:", 
            all_options, 
            index=default_index
        )

        if selected_option == "All Gameweeks":
            df_display = df_fixtures
        else:
            selected_gw_num = int(selected_option.replace("Gameweek ", ""))
            df_display = df_fixtures[df_fixtures["GW"] == selected_gw_num]

        st.dataframe(df_display, use_container_width=True, hide_index=True, height=500)
else:
    st.error("Failed to load season fixtures. Please check your internet connection or league ID.")
