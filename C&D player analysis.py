import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(page_title="Craft & Draft Squad & Player Analytics", layout="wide")

# Auto-refresh every 60 seconds (prevents memory leaks on cloud runners)
st_autorefresh(interval=60000, key="cnd_player_analysis_refresh")

LEAGUE_ID = 858
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BOOTSTRAP_URL = "https://draft.premierleague.com/api/bootstrap-static"
LEAGUE_URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
GAME_URL = "https://draft.premierleague.com/api/game"
ENTRY_BASE_URL = "https://draft.premierleague.com/api/entry/{}/event/{}"


@st.cache_data(ttl=120)
def fetch_json(url):
    """Safely fetch JSON data from the FPL Draft API."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_bootstrap_data():
    """Fetches and maps elements, teams, positions, and finished gameweeks."""
    data = fetch_json(BOOTSTRAP_URL)
    if not data or not isinstance(data, dict):
        data = fetch_json(GAME_URL)

    elements_map = {}
    positions_map = {}
    teams_map = {}
    finished_gws = []

    if data and isinstance(data, dict):
        # 1. Map Positions
        for p in data.get("element_types", []):
            if isinstance(p, dict):
                positions_map[p.get("id")] = p.get("singular_name_short", "N/A")

        # 2. Map Teams
        for t in data.get("teams", []):
            if isinstance(t, dict):
                teams_map[t.get("id")] = t.get("short_name", t.get("name", "N/A"))

        # 3. Map Players
        for el in data.get("elements", []):
            if isinstance(el, dict):
                elements_map[el.get("id")] = {
                    "web_name": el.get("web_name", f"Player {el.get('id')}"),
                    "full_name": f"{el.get('first_name', '')} {el.get('second_name', '')}".strip(),
                    "position": positions_map.get(el.get("element_type"), "N/A"),
                    "team": teams_map.get(el.get("team"), "N/A"),
                    "total_points": el.get("total_points", 0),
                    "goals": el.get("goals_scored", 0),
                    "assists": el.get("assists", 0),
                    "clean_sheets": el.get("clean_sheets", 0),
                    "minutes": el.get("minutes", 0),
                }

        # 4. Safe Gameweek Extraction (Fixes AttributeError)
        events_obj = data.get("events")
        events_raw = []
        if isinstance(events_obj, dict):
            events_raw = events_obj.get("data", [])
        elif isinstance(events_obj, list):
            events_raw = events_obj

        finished_gws = [
            e["id"]
            for e in events_raw
            if isinstance(e, dict) and e.get("finished") and "id" in e
        ]

    # Fallback to GW1 if no GWs finished yet
    if not finished_gws:
        finished_gws = [1]

    return elements_map, positions_map, teams_map, sorted(finished_gws)


def get_league_entries():
    """Retrieve managers and team mappings from the league details endpoint."""
    league_data = fetch_json(LEAGUE_URL)
    entries = []
    if league_data and isinstance(league_data, dict):
        raw_entries = league_data.get("league_entries", [])
        for e in raw_entries:
            if isinstance(e, dict):
                entries.append({
                    "id": e.get("id"),
                    "entry_id": e.get("entry_id"),
                    "manager_name": f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip(),
                    "team_name": e.get("entry_name", "Team"),
                    "display_name": f"{e.get('entry_name')} ({e.get('player_first_name')} {e.get('player_last_name')})",
                })
    return entries


def analyze_squad_usage(entries, player_map, finished_gws):
    """Parses each manager's lineup across gameweeks to assess starter vs bench usage."""
    squad_stats = []

    for entry in entries:
        entry_id = entry["entry_id"]
        if not entry_id:
            continue

        started_points = 0
        benched_points = 0
        active_lineup_count = 0

        # Sample the most recent finished gameweeks (up to last 5 to keep requests fast)
        recent_gws = finished_gws[-5:] if len(finished_gws) > 5 else finished_gws

        for gw in recent_gws:
            gw_data = fetch_json(ENTRY_BASE_URL.format(entry_id, gw))
            if not gw_data or not isinstance(gw_data, dict):
                continue

            picks = gw_data.get("picks", [])
            for p in picks:
                if not isinstance(p, dict):
                    continue
                p_id = p.get("element")
                pos_order = p.get("position", 1)  # 1-11 starter, 12-15 bench
                p_info = player_map.get(p_id, {})
                
                # Use total points divided by GW span as proxy if live pick pts unavailable
                approx_pts = p_info.get("total_points", 0) / max(len(finished_gws), 1)

                if pos_order <= 11:
                    started_points += approx_pts
                    active_lineup_count += 1
                else:
                    benched_points += approx_pts

        total_pts = started_points + benched_points
        bench_efficiency = (
            round((started_points / total_pts) * 100, 1) if total_pts > 0 else 100.0
        )

        squad_stats.append({
            "Manager": entry["display_name"],
            "Team": entry["team_name"],
            "Starting Squad Contribution (Est Pts)": round(started_points, 1),
            "Benched Points (Est Pts)": round(benched_points, 1),
            "Lineup Efficiency (%)": f"{bench_efficiency}%",
        })

    return pd.DataFrame(squad_stats)


# --- App Header ---
st.title("📊 Craft & Draft Squad & Player Analytics")
st.caption(f"Target League: **{LEAGUE_ID}**")

player_map, pos_map, team_map, finished_gws = load_bootstrap_data()
entries = get_league_entries()

if player_map and entries:
    # 1. Global Player Database View
    st.subheader("⚽ Premier League Player Pool Performance")

    player_records = []
    for p_id, p_info in player_map.items():
        player_records.append({
            "Player": p_info["web_name"],
            "Full Name": p_info["full_name"],
            "Club": p_info["team"],
            "Position": p_info["position"],
            "Total Points": p_info["total_points"],
            "Goals": p_info["goals"],
            "Assists": p_info["assists"],
            "Clean Sheets": p_info["clean_sheets"],
            "Minutes": p_info["minutes"],
        })

    df_players = pd.DataFrame(player_records)

    # Filtering Controls
    c1, c2, c3 = st.columns(3)
    pos_filter = c1.selectbox(
        "Position Filter:", ["All Positions"] + sorted(list(pos_map.values()))
    )
    club_filter = c2.selectbox(
        "Club Filter:", ["All Clubs"] + sorted(list(team_map.values()))
    )
    min_points = c3.slider("Minimum Total Points:", 0, 250, 0)

    df_filtered_players = df_players.copy()
    if pos_filter != "All Positions":
        df_filtered_players = df_filtered_players[
            df_filtered_players["Position"] == pos_filter
        ]
    if club_filter != "All Clubs":
        df_filtered_players = df_filtered_players[
            df_filtered_players["Club"] == club_filter
        ]
    df_filtered_players = df_filtered_players[
        df_filtered_players["Total Points"] >= min_points
    ]

    df_filtered_players.sort_values(by="Total Points", ascending=False, inplace=True)
    st.dataframe(
        df_filtered_players, use_container_width=True, hide_index=True, height=450
    )

    st.divider()

    # 2. Squad Usage & Starting Lineup Efficiency
    st.subheader("🧠 Manager Lineup Selection & Squad Usage")
    st.caption("Analyzes starting lineup optimization vs points left on the bench.")

    with st.spinner("Analyzing recent manager squad selections..."):
        df_squad_usage = analyze_squad_usage(entries, player_map, finished_gws)

    if not df_squad_usage.empty:
        df_squad_usage.sort_values(
            by="Starting Squad Contribution (Est Pts)", ascending=False, inplace=True
        )
        st.dataframe(df_squad_usage, use_container_width=True, hide_index=True)
    else:
        st.info("Squad analysis will populate as fixtures progress.")

else:
    st.error("Connecting to Premier League API... Please refresh if data does not load.")
