import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Full Season Fixtures", layout="wide")
st_autorefresh(interval=10000, key="fpl_refresh_app2")

LEAGUE_ID = 4159
URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
HEADERS = {"User-Agent": "Mozilla/5.0"}

@st.cache_data(ttl=5)
def fetch_data():
    try:
        res = requests.get(URL, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None

data = fetch_data()

if data:
    st.subheader("📅 Full Season Fixture Schedule & Scores")
    entries = data.get("league_entries", [])
    entry_map = {
        e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
        for e in entries
    }

    matches_raw = data.get("matches", [])
    fixtures_list = [{
        "GW": m.get("event"),
        "Home Team": entry_map.get(m.get("league_entry_1")),
        "Home Score": m.get("league_entry_1_points", 0),
        "Away Score": m.get("league_entry_2_points", 0),
        "Away Team": entry_map.get(m.get("league_entry_2")),
        "Status": "Finished" if m.get("finished") else ("Live" if m.get("started") else "Scheduled")
    } for m in matches_raw]

    df_fixtures = pd.DataFrame(fixtures_list)
    
    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)
        
        # Filter option
        all_gws = ["All Gameweeks"] + sorted(list(df_fixtures["GW"].unique()))
        selected_option = st.selectbox("Filter Schedule:", all_gws)

        if selected_option != "All Gameweeks":
            df_display = df_fixtures[df_fixtures["GW"] == selected_option]
        else:
            df_display = df_fixtures

        st.dataframe(df_display, use_container_width=True, hide_index=True, height=500)
else:
    st.error("Failed to load season fixtures.")
