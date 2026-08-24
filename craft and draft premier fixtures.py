import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Current Gameweek Fixtures", layout="wide")
st_autorefresh(interval=30000, key="fpl_refresh_cur_gw")

LEAGUE_ID = 858
URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
BOOTSTRAP_URL = "https://draft.premierleague.com/api/game"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


@st.cache_data(ttl=10)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


data = fetch_json(URL)

if data and isinstance(data, dict):
    # 1. Accurately detect Current Gameweek from FPL official metadata
    league_info = data.get("league", {})
    current_gw = league_info.get("current_event")

    # Fallback to bootstrap /game endpoint if current_event is null/missing
    if not current_gw:
        game_data = fetch_json(BOOTSTRAP_URL)
        if game_data and isinstance(game_data, dict):
            current_gw = game_data.get("current_event")

    # Final safety fallback to GW1
    if not current_gw:
        current_gw = 1

    st.subheader("📅 Current Gameweek Fixtures & Scores")

    entries = data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries
        if isinstance(e, dict)
    }

    matches_raw = data.get("matches", [])

    fixtures_list = []
    for m in matches_raw:
        if not isinstance(m, dict):
            continue

        gw = m.get("event")
        is_started = m.get("started", False)
        is_finished = m.get("finished", False)

        status = (
            "Finished" if is_finished else ("Live" if is_started else "Scheduled")
        )
        h_score = (
            m.get("league_entry_1_points", 0)
            if (is_started or is_finished)
            else "-"
        )
        a_score = (
            m.get("league_entry_2_points", 0)
            if (is_started or is_finished)
            else "-"
        )

        fixtures_list.append({
            "GW": gw,
            "Home Team": entry_map.get(
                m.get("league_entry_1"), f"Entry {m.get('league_entry_1')}"
            ),
            "Home Score": h_score,
            "Away Score": a_score,
            "Away Team": entry_map.get(
                m.get("league_entry_2"), f"Entry {m.get('league_entry_2')}"
            ),
            "Status": status,
        })

    df_fixtures = pd.DataFrame(fixtures_list)

    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)

        # 2. Build Gameweek list and set default to current_gw
        unique_gws = sorted(
            [int(g) for g in df_fixtures["GW"].dropna().unique()]
        )
        gw_options = [f"Gameweek {g}" for g in unique_gws] + ["All Gameweeks"]

        target_label = f"Gameweek {current_gw}"
        default_idx = (
            gw_options.index(target_label)
            if target_label in gw_options
            else 0
        )

        selected_option = st.selectbox(
            "Select Gameweek:", gw_options, index=default_idx
        )

        if selected_option == "All Gameweeks":
            df_display = df_fixtures
        else:
            selected_gw_num = int(selected_option.replace("Gameweek ", ""))
            df_display = df_fixtures[df_fixtures["GW"] == selected_gw_num]

        st.caption(f"Showing live updates for **{selected_option}**")
        st.dataframe(
            df_display, use_container_width=True, hide_index=True, height=450
        )
else:
    st.error("Failed to load league data from FPL Draft API.")
