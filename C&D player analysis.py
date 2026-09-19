import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(page_title="Craft & Draft Squad & Player Analytics", layout="wide")

# Auto-refresh every 60 seconds
st_autorefresh(interval=60000, key="cnd_player_analysis_refresh")

CHAMPIONSHIP_LEAGUE_ID = 4159
PREMIER_LEAGUE_ID = 858
LEAGUE_IDS = [PREMIER_LEAGUE_ID, CHAMPIONSHIP_LEAGUE_ID]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BOOTSTRAP_URL = "https://draft.premierleague.com/api/bootstrap-static"
LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"
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
    current_gw = None

    if data and isinstance(data, dict):
        current_gw = data.get("current_event")

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

        # 4. Safe Gameweek Extraction
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

    if not finished_gws:
        finished_gws = [1]

    return elements_map, positions_map, teams_map, sorted(finished_gws), current_gw


def get_all_league_entries():
    """Retrieve managers and team mappings across both leagues."""
    all_entries = []
    for l_id in LEAGUE_IDS:
        league_data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if league_data and isinstance(league_data, dict):
            l_name = league_data.get("league", {}).get("name", f"League {l_id}")
            raw_entries = league_data.get("league_entries", [])
            for e in raw_entries:
                if isinstance(e, dict):
                    all_entries.append({
                        "id": e.get("id"),
                        "entry_id": e.get("entry_id"),
                        "league_id": l_id,
                        "league_name": l_name,
                        "manager_name": f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip(),
                        "team_name": e.get("entry_name", "Team"),
                        "display_name": f"{e.get('entry_name')} ({e.get('player_first_name')} {e.get('player_last_name')})",
                    })
    return all_entries


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

        league_label = "C&D Championship" if entry["league_id"] == 4159 else "C&D Premier"

        squad_stats.append({
            "League": league_label,
            "Manager": entry["display_name"],
            "Team": entry["team_name"],
            "Starting Squad Contribution (Est Pts)": round(started_points, 1),
            "Benched Points (Est Pts)": round(benched_points, 1),
            "Lineup Efficiency (%)": f"{bench_efficiency}%",
        })

    return pd.DataFrame(squad_stats)


# --- Load Core Data ---
player_map, pos_map, team_map, finished_gws, bootstrap_gw = load_bootstrap_data()
champ_data = fetch_json(LEAGUE_URL_FMT.format(CHAMPIONSHIP_LEAGUE_ID))
all_entries = get_all_league_entries()

# ==========================================================
# 1. 🏆 CHAMPIONSHIP STANDINGS TABLE
# ==========================================================
st.subheader("🏆 Championship Standings")

if champ_data and isinstance(champ_data, dict):
    champ_entries = champ_data.get("league_entries", [])
    champ_entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in champ_entries
        if isinstance(e, dict)
    }

    matches_raw = champ_data.get("matches", [])
    entry_played_count = {e.get("id"): 0 for e in champ_entries if isinstance(e, dict)}
    for m in matches_raw:
        if isinstance(m, dict) and (m.get("started") or m.get("finished")):
            e1 = m.get("league_entry_1")
            e2 = m.get("league_entry_2")
            if e1 in entry_played_count:
                entry_played_count[e1] += 1
            if e2 in entry_played_count:
                entry_played_count[e2] += 1

    standings_raw = champ_data.get("standings", [])
    standings_rows = []

    for s in standings_raw:
        if not isinstance(s, dict):
            continue

        e_id = s.get("league_entry")
        team_display = champ_entry_map.get(e_id, f"Team {e_id}")

        won = s.get("matches_won", 0)
        drawn = s.get("matches_drawn", 0)
        lost = s.get("matches_lost", 0)

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
        st.dataframe(df_standings, use_container_width=True, hide_index=True)
    else:
        st.info("Standings will appear once matches have commenced.")

    st.divider()

    # ==========================================================
    # 2. 📅 CHAMPIONSHIP FIXTURES & SCORES TABLE
    # ==========================================================
    st.subheader("📅 Championship Fixtures & Scores")

    current_gw = champ_data.get("league", {}).get("current_event") or bootstrap_gw or 1

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
            "Home Team": champ_entry_map.get(m.get("league_entry_1"), f"Entry {m.get('league_entry_1')}"),
            "Home Score": h_score,
            "Away Score": a_score,
            "Away Team": champ_entry_map.get(m.get("league_entry_2"), f"Entry {m.get('league_entry_2')}"),
            "Status": status,
        })

    df_fixtures = pd.DataFrame(fixtures_list)

    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)

        unique_gws = sorted([int(g) for g in df_fixtures["GW"].dropna().unique()])
        gw_options = [f"Gameweek {g}" for g in unique_gws] + ["All Gameweeks"]

        target_label = f"Gameweek {current_gw}"
        default_idx = gw_options.index(target_label) if target_label in gw_options else 0

        selected_option = st.selectbox("Select Gameweek:", gw_options, index=default_idx)

        if selected_option == "All Gameweeks":
            df_display = df_fixtures
        else:
            selected_gw_num = int(selected_option.replace("Gameweek ", ""))
            df_display = df_fixtures[df_fixtures["GW"] == selected_gw_num]

        st.caption(f"Showing live fixtures for **{selected_option}**")
        st.dataframe(df_display, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("No fixtures found.")
else:
    st.error("Failed to load Championship data from FPL Draft API.")

st.divider()

# ==========================================================
# 3. MANAGER LINEUP SELECTION & SQUAD USAGE
# ==========================================================
st.subheader("🧠 Manager Lineup Selection & Squad Usage")
st.caption("Analyzes starting lineup optimization vs points left on the bench.")

# Filter by League with requested custom labels
league_filter = st.radio(
    "Filter Squad Analysis by League:",
    ["All Leagues Combined", "C&D Premier", "C&D Championship"],
    horizontal=True,
)

selected_entries = all_entries
if league_filter == "C&D Premier":
    selected_entries = [e for e in all_entries if e["league_id"] == PREMIER_LEAGUE_ID]
elif league_filter == "C&D Championship":
    selected_entries = [e for e in all_entries if e["league_id"] == CHAMPIONSHIP_LEAGUE_ID]

with st.spinner("Analyzing manager squad selections across leagues..."):
    df_squad_usage = analyze_squad_usage(selected_entries, player_map, finished_gws)

if not df_squad_usage.empty:
    df_squad_usage.sort_values(
        by="Starting Squad Contribution (Est Pts)", ascending=False, inplace=True
    )
    st.dataframe(df_squad_usage, use_container_width=True, hide_index=True)
else:
    st.info("Squad analysis will populate as fixtures progress.")

st.divider()

# ==========================================================
# 4. PREMIER LEAGUE PLAYER POOL PERFORMANCE
# ==========================================================
st.subheader("⚽ Premier League Player Pool Performance")

if player_map:
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
        df_filtered_players, use_container_width=True, hide_index=True, height=400
    )
else:
    st.info("Player data could not be loaded.")
