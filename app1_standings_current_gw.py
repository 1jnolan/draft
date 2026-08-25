import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="League Standings & Fixtures", layout="wide")
st_autorefresh(interval=30000, key="fpl_refresh_league_full")

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
    # 1. Accurately detect Current Gameweek
    league_info = data.get("league", {})
    current_gw = league_info.get("current_event")

    if not current_gw:
        game_data = fetch_json(BOOTSTRAP_URL)
        if game_data and isinstance(game_data, dict):
            current_gw = game_data.get("current_event")

    if not current_gw:
        current_gw = 1

    # Map team names and manager names
    entries = data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries
        if isinstance(e, dict)
    }

    # Pre-calculate active/completed matches per entry from the match schedule
    matches_raw = data.get("matches", [])
    entry_played_count = {e.get("id"): 0 for e in entries if isinstance(e, dict)}
    for m in matches_raw:
        if isinstance(m, dict) and (m.get("started") or m.get("finished")):
            e1 = m.get("league_entry_1")
            e2 = m.get("league_entry_2")
            if e1 in entry_played_count:
                entry_played_count[e1] += 1
            if e2 in entry_played_count:
                entry_played_count[e2] += 1

    # ==========================================
    # 1. LEAGUE STANDINGS TABLE
    # ==========================================
    st.subheader(f"🏆 {league_info.get('name', 'League')} Standings")

    standings_raw = data.get("standings", [])
    standings_rows = []

    for s in standings_raw:
        if not isinstance(s, dict):
            continue

        e_id = s.get("league_entry")
        team_display = entry_map.get(e_id, f"Team {e_id}")

        won = s.get("matches_won", 0)
        drawn = s.get("matches_drawn", 0)
        lost = s.get("matches_lost", 0)

        # Calculate actual games played (falls back to schedule counter during active gameweeks)
        actual_played = won + drawn + lost
        if actual_played == 0 and e_id in entry_played_count:
            actual_played = entry_played_count[e_id]

        standings_rows.append({
            "Rank": s.get("rank", "-"),
            "Team & Manager": team_display,
            "Played": actual_played,
            "Won": won,
            "Drawn": drawn,
            "Lost": lost,
            "Points For": s.get("points_for", 0),
            "Points Against": s.get("points_against", 0),
            "Total Pts": s.get("total", 0),
        })

    df_standings = pd.DataFrame(standings_rows)

    if not df_standings.empty:
        df_standings.sort_values(by=["Rank"], inplace=True)
        st.dataframe(
            df_standings, use_container_width=True, hide_index=True
        )
    else:
        st.info("Standings will appear once matches have commenced.")

    st.divider()

    # ==========================================
    # 2. FIXTURES & SCORES TABLE
    # ==========================================
    st.subheader("📅 Fixtures & Scores")

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

        st.caption(f"Showing live fixtures for **{selected_option}**")
        st.dataframe(
            df_display, use_container_width=True, hide_index=True, height=350
        )

else:
    st.error("Failed to load league data from FPL Draft API.")
