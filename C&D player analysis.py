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
TX_URL_FMT = "https://draft.premierleague.com/api/draft/league/{}/transactions"
TRADES_URL_FMT = "https://draft.premierleague.com/api/draft/league/{}/trades"
EVENT_LIVE_URL = "https://draft.premierleague.com/api/event/{}/live"


@st.cache_data(ttl=120)
def fetch_json(url):
    """Safely fetch JSON data from the FPL Draft API."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=30)
def fetch_gw_live_scores(gw):
    """Fetches point tallies for all players in a specific gameweek."""
    try:
        res = requests.get(EVENT_LIVE_URL.format(gw), headers=HEADERS, timeout=8)
        if res.status_code == 200:
            data = res.json()
            elements = data.get("elements", {})
            return {
                int(k): v.get("stats", {}).get("total_points", 0)
                for k, v in elements.items()
            }
    except Exception:
        pass
    return {}


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


@st.cache_data(ttl=180)
def fetch_league_element_ownership(entries, current_gw):
    """Scrapes the most recent roster picks for each manager in both leagues."""
    prem_owners = {}
    champ_owners = {}
    target_gw = max(1, current_gw or 1)

    for entry in entries:
        entry_id = entry.get("entry_id")
        if not entry_id:
            continue

        l_id = entry.get("league_id")
        mgr_name = entry.get("manager_name") or entry.get("team_name")

        roster_data = fetch_json(ENTRY_BASE_URL.format(entry_id, target_gw))
        if (not roster_data or "picks" not in roster_data) and target_gw > 1:
            roster_data = fetch_json(ENTRY_BASE_URL.format(entry_id, target_gw - 1))

        if roster_data and isinstance(roster_data, dict):
            for pick in roster_data.get("picks", []):
                p_id = pick.get("element")
                if p_id:
                    if l_id == PREMIER_LEAGUE_ID:
                        prem_owners[p_id] = mgr_name
                    elif l_id == CHAMPIONSHIP_LEAGUE_ID:
                        champ_owners[p_id] = mgr_name

    return prem_owners, champ_owners


def parse_standings(league_data):
    """Processes standings dataframe from league details."""
    if not league_data or not isinstance(league_data, dict):
        return pd.DataFrame()

    entries = league_data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries
        if isinstance(e, dict)
    }

    matches_raw = league_data.get("matches", [])
    entry_played_count = {e.get("id"): 0 for e in entries if isinstance(e, dict)}
    for m in matches_raw:
        if isinstance(m, dict) and (m.get("started") or m.get("finished")):
            e1 = m.get("league_entry_1")
            e2 = m.get("league_entry_2")
            if e1 in entry_played_count:
                entry_played_count[e1] += 1
            if e2 in entry_played_count:
                entry_played_count[e2] += 1

    standings_raw = league_data.get("standings", [])
    standings_rows = []

    for s in standings_raw:
        if not isinstance(s, dict):
            continue

        e_id = s.get("league_entry")
        team_display = entry_map.get(e_id, f"Team {e_id}")

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
    return df_standings


def parse_fixtures(league_data):
    """Processes fixtures and scores list from league details."""
    if not league_data or not isinstance(league_data, dict):
        return pd.DataFrame(), None

    entries = league_data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries
        if isinstance(e, dict)
    }

    current_gw = league_data.get("league", {}).get("current_event")
    matches_raw = league_data.get("matches", [])
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
            "Status": status,
        })

    df_fixtures = pd.DataFrame(fixtures_list)
    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)

    return df_fixtures, current_gw


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
                pos_order = p.get("position", 1)
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


def calculate_manager_of_the_year(prem_data, champ_data):
    """
    Evaluates completed gameweeks across both leagues, finds the manager with
    the highest gameweek score on each week, and awards 1 point per award.
    """
    leagues_payload = [
        ("C&D Premier", prem_data),
        ("C&D Championship", champ_data),
    ]

    # Map managers: (league_name, entry_id) -> manager info
    manager_records = {}
    gw_scores = {}  # {gw: [ {"mgr_key": (league, id), "display": ..., "team": ..., "league": ..., "score": ...} ]}

    for l_label, l_data in leagues_payload:
        if not l_data or not isinstance(l_data, dict):
            continue

        entries = l_data.get("league_entries", [])
        entry_meta = {}
        for e in entries:
            if isinstance(e, dict):
                e_id = e.get("id")
                disp = f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip()
                t_name = e.get("entry_name", "Team")
                entry_meta[e_id] = {
                    "manager": disp or t_name,
                    "team": t_name,
                    "league": l_label,
                }
                key = (l_label, e_id)
                manager_records[key] = {
                    "Manager": disp or t_name,
                    "Team": t_name,
                    "League": l_label,
                    "motw_awards": 0,
                    "total_points_scored": 0,
                    "gws_won": [],
                }

        # Parse match events for completed/started gameweeks
        for m in l_data.get("matches", []):
            if not isinstance(m, dict):
                continue
            is_finished = m.get("finished", False)
            if not is_finished:
                continue

            gw = m.get("event")
            if not gw:
                continue

            e1 = m.get("league_entry_1")
            e2 = m.get("league_entry_2")
            s1 = m.get("league_entry_1_points", 0)
            s2 = m.get("league_entry_2_points", 0)

            if gw not in gw_scores:
                gw_scores[gw] = []

            if e1 in entry_meta:
                gw_scores[gw].append({
                    "mgr_key": (l_label, e1),
                    "score": s1,
                })
                manager_records[(l_label, e1)]["total_points_scored"] += s1

            if e2 in entry_meta:
                gw_scores[gw].append({
                    "mgr_key": (l_label, e2),
                    "score": s2,
                })
                manager_records[(l_label, e2)]["total_points_scored"] += s2

    # Award MOTW points for each finished gameweek across both leagues
    for gw, score_list in sorted(gw_scores.items()):
        if not score_list:
            continue
        max_score = max(item["score"] for item in score_list)
        if max_score > 0:
            winners = [item["mgr_key"] for item in score_list if item["score"] == max_score]
            for w_key in winners:
                if w_key in manager_records:
                    manager_records[w_key]["motw_awards"] += 1
                    manager_records[w_key]["gws_won"].append(f"GW {gw} ({max_score} pts)")

    rows = []
    for info in manager_records.values():
        gws_won_str = ", ".join(info["gws_won"]) if info["gws_won"] else "-"
        rows.append({
            "League": info["League"],
            "Manager": info["Manager"],
            "Team": info["Team"],
            "Manager of the Week Awards": info["motw_awards"],
            "Overall Points Scored": info["total_points_scored"],
            "Gameweeks Won": gws_won_str,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(
            by=["Manager of the Week Awards", "Overall Points Scored"],
            ascending=[False, False],
            inplace=True,
        )
        df.reset_index(drop=True, inplace=True)
        df.insert(0, "Rank", range(1, len(df) + 1))
    return df


# --- Load Core Data ---
player_map, pos_map, team_map, finished_gws, bootstrap_gw = load_bootstrap_data()
champ_data = fetch_json(LEAGUE_URL_FMT.format(CHAMPIONSHIP_LEAGUE_ID))
prem_data = fetch_json(LEAGUE_URL_FMT.format(PREMIER_LEAGUE_ID))
all_entries = get_all_league_entries()

# Determine active gameweek
detected_active_gw = (
    (prem_data and prem_data.get("league", {}).get("current_event"))
    or (champ_data and champ_data.get("league", {}).get("current_event"))
    or bootstrap_gw
    or 1
)

prem_owners, champ_owners = fetch_league_element_ownership(all_entries, detected_active_gw)

# ==========================================================
# 1. 🏆 CRAFT AND DRAFT LEAGUE STANDINGS
# ==========================================================
st.subheader("🏆 Craft and Draft League Standings")

standings_league_choice = st.radio(
    "Select League Standings:",
    ["Premier Standings", "Championship Standings"],
    horizontal=True,
    key="standings_selector",
)

selected_standings_data = prem_data if standings_league_choice == "Premier Standings" else champ_data
df_standings = parse_standings(selected_standings_data)

if not df_standings.empty:
    st.dataframe(df_standings, use_container_width=True, hide_index=True)
else:
    st.info("Standings will appear once matches have commenced.")

st.divider()

# ==========================================================
# 2. 📅 CRAFT AND DRAFT FIXTURES & SCORES
# ==========================================================
fixtures_league_choice = st.radio(
    "Select League Fixtures:",
    ["Premier Fixtures", "Championship Fixtures"],
    horizontal=True,
    key="fixtures_selector",
)

st.subheader(f"📅 {fixtures_league_choice} & Scores")

selected_fixtures_data = prem_data if fixtures_league_choice == "Premier Fixtures" else champ_data
df_fixtures, detected_gw = parse_fixtures(selected_fixtures_data)
active_gw = detected_gw or bootstrap_gw or 1

if not df_fixtures.empty:
    unique_gws = sorted([int(g) for g in df_fixtures["GW"].dropna().unique()])
    gw_options = [f"Gameweek {g}" for g in unique_gws] + ["All Gameweeks"]

    target_label = f"Gameweek {active_gw}"
    default_idx = gw_options.index(target_label) if target_label in gw_options else 0

    selected_option = st.selectbox(
        "Select Gameweek:",
        gw_options,
        index=default_idx,
        key=f"gw_select_{fixtures_league_choice}",
    )

    if selected_option == "All Gameweeks":
        df_display = df_fixtures
    else:
        selected_gw_num = int(selected_option.replace("Gameweek ", ""))
        df_display = df_fixtures[df_fixtures["GW"] == selected_gw_num]

    st.caption(f"Showing live fixtures for **{selected_option}**")
    st.dataframe(df_display, use_container_width=True, hide_index=True, height=350)
else:
    st.info("No fixtures found.")

st.divider()

# ==========================================================
# 3. ⚽ PREMIER LEAGUE PLAYER POOL PERFORMANCE
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
            "C&D Premier Owner": prem_owners.get(p_id, "Free Agent"),
            "C&D Championship Owner": champ_owners.get(p_id, "Free Agent"),
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

st.divider()

# ==========================================================
# 4. 🧠 MANAGER LINEUP SELECTION & SQUAD USAGE
# ==========================================================
st.subheader("🧠 Manager Lineup Selection & Squad Usage")
st.caption("Analyzes starting lineup optimization vs points left on the bench.")

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
# 5. 👑 MANAGER OF THE YEAR TABLE
# ==========================================================
st.subheader("🏆 Manager of the Year")
st.caption("Awards **1 point** per completed Gameweek to the manager with the single highest match score across both C&D Premier & Championship.")

df_moty = calculate_manager_of_the_year(prem_data, champ_data)

if not df_moty.empty:
    st.dataframe(df_moty, use_container_width=True, hide_index=True)
else:
    st.info("Manager of the Year awards will be calculated as Gameweeks finish.")

st.divider()

# ==========================================================
# 6. 🔄 WAIVER & TRADE MARKET TRACKER
# ==========================================================
st.subheader("🔄 Waiver & Trade Market Tracker")

market_league_choice = st.radio(
    "Select League for Market Tracker:",
    ["C&D Premier", "C&D Championship"],
    horizontal=True,
    key="market_league_selector",
)

active_market_league_id = PREMIER_LEAGUE_ID if market_league_choice == "C&D Premier" else CHAMPIONSHIP_LEAGUE_ID
active_market_league_data = prem_data if market_league_choice == "C&D Premier" else champ_data

tx_data = fetch_json(TX_URL_FMT.format(active_market_league_id))
trades_data = fetch_json(TRADES_URL_FMT.format(active_market_league_id))

if active_market_league_data and isinstance(active_market_league_data, dict):
    m_entries = active_market_league_data.get("league_entries", [])
    m_id_to_name = {}
    m_manager_names = []

    for e in m_entries:
        if isinstance(e, dict):
            name = f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
            m_manager_names.append(name)
            if "id" in e:
                m_id_to_name[e["id"]] = name
            if "entry_id" in e:
                m_id_to_name[e["entry_id"]] = name

    # Transaction & Point Calculations
    m_player_counts = {}
    m_transfer_log = []
    m_gw_scores_cache = {}

    m_manager_stats = {
        m_name: {
            "waiver_att": 0,
            "waiver_succ": 0,
            "fa_succ": 0,
            "pts_in": 0,
            "pts_out": 0,
            "gws": set(),
        }
        for m_name in m_manager_names
    }

    m_manager_gw_pts_in = {m_name: {} for m_name in m_manager_names}
    m_all_active_gws = set()

    if tx_data and isinstance(tx_data, dict):
        transactions = tx_data.get("transactions", [])

        for tx in transactions:
            if not isinstance(tx, dict):
                continue

            raw_id = tx.get("entry") or tx.get("league_entry")
            m_name = m_id_to_name.get(raw_id)
            kind = tx.get("kind")  # 'w' = waiver, 'f' = free agency
            result = tx.get("result")  # 'a' = accepted
            gw = tx.get("event")
            is_successful = (result == "a") or (kind == "f")

            if m_name and m_name in m_manager_stats:
                if gw:
                    m_manager_stats[m_name]["gws"].add(gw)

                if kind == "w":
                    m_manager_stats[m_name]["waiver_att"] += 1
                    if result == "a":
                        m_manager_stats[m_name]["waiver_succ"] += 1
                elif kind == "f":
                    m_manager_stats[m_name]["fa_succ"] += 1

            if is_successful and gw:
                m_all_active_gws.add(gw)
                el_in = tx.get("element_in")
                el_out = tx.get("element_out")
                move_type = "Waiver" if kind == "w" else "Free Agency"

                if gw not in m_gw_scores_cache:
                    m_gw_scores_cache[gw] = fetch_gw_live_scores(gw)
                current_gw_scores = m_gw_scores_cache[gw]

                in_pts = current_gw_scores.get(el_in, 0) if el_in else 0
                out_pts = current_gw_scores.get(el_out, 0) if el_out else 0
                net_pts = in_pts - out_pts

                if m_name and m_name in m_manager_stats:
                    m_manager_stats[m_name]["pts_in"] += in_pts
                    m_manager_stats[m_name]["pts_out"] += out_pts
                    m_manager_gw_pts_in[m_name][gw] = m_manager_gw_pts_in[m_name].get(gw, 0) + in_pts

                if el_in:
                    if el_in not in m_player_counts:
                        m_player_counts[el_in] = {"in": 0, "out": 0}
                    m_player_counts[el_in]["in"] += 1

                if el_out:
                    if el_out not in m_player_counts:
                        m_player_counts[el_out] = {"in": 0, "out": 0}
                    m_player_counts[el_out]["out"] += 1

                if out_pts > 0:
                    tx_pct = round(((in_pts - out_pts) / out_pts) * 100, 1)
                    tx_pct_str = f"+{tx_pct}%" if tx_pct > 0 else f"{tx_pct}%"
                elif in_pts > 0:
                    tx_pct_str = "+100% (Pure Gain)"
                else:
                    tx_pct_str = "0.0%"

                p_in_info = (player_map or {}).get(el_in, {"web_name": f"Player {el_in}", "team": "-", "position": "-"})
                p_out_info = (player_map or {}).get(el_out, {"web_name": f"Player {el_out}", "team": "-", "position": "-"})

                m_transfer_log.append({
                    "Gameweek": f"GW {gw}",
                    "Manager": m_name or f"Manager ({raw_id})",
                    "Type": move_type,
                    "Player In": f"{p_in_info['web_name']} ({p_in_info['team']})",
                    "Pts In": in_pts,
                    "Player Out": f"{p_out_info['web_name']} ({p_out_info['team']})",
                    "Pts Out": out_pts,
                    "Net Pts": f"+{net_pts}" if net_pts > 0 else str(net_pts),
                    "Transfer ROI": tx_pct_str,
                })

    # Sub-section 6.1: Manager Waiver Activity & ROI Table
    st.markdown("#### 📈 Manager Waiver Activity & Net Points Impact")
    tx_list = []
    for m_name, stats in m_manager_stats.items():
        att = stats["waiver_att"]
        succ = stats["waiver_succ"]
        fa = stats["fa_succ"]
        total_changes = succ + fa
        rate = round((succ / att) * 100, 1) if att > 0 else 0.0
        p_in = stats["pts_in"]
        p_out = stats["pts_out"]
        net_diff = p_in - p_out

        if p_out > 0:
            imp_pct = round(((p_in - p_out) / p_out) * 100, 1)
            imp_pct_str = f"+{imp_pct}%" if imp_pct > 0 else f"{imp_pct}%"
        elif p_in > 0:
            imp_pct_str = "+100.0%"
        else:
            imp_pct_str = "0.0%"

        tx_list.append({
            "Manager": m_name,
            "Total Successful Changes": total_changes,
            "Pts from Players IN": p_in,
            "Pts from Players OUT": p_out,
            "Net Points Diff": f"+{net_diff}" if net_diff > 0 else str(net_diff),
            "Overall ROI (%)": imp_pct_str,
            "Waivers Won": succ,
            "Free Agent Pickups": fa,
            "Waiver Success Rate": f"{rate}%",
            "Active GWs": len(stats["gws"]),
        })

    df_tx = pd.DataFrame(tx_list)
    if not df_tx.empty:
        df_tx["sort_net"] = df_tx["Net Points Diff"].astype(int)
        df_tx.sort_values(by=["sort_net", "Total Successful Changes"], ascending=[False, False], inplace=True)
        df_tx.drop(columns=["sort_net"], inplace=True)
        st.dataframe(df_tx, use_container_width=True, hide_index=True)
    else:
        st.info("No transaction stats recorded.")

    # Sub-section 6.2: Manager-to-Manager Trades Tracker
    st.markdown("#### 🤝 Manager-to-Manager Trades Tracker")
    trade_counts = {m_name: 0 for m_name in m_manager_names}
    if trades_data and isinstance(trades_data, dict):
        trades = trades_data.get("trades", [])
        for t in trades:
            if isinstance(t, dict) and t.get("state") == "p":
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                name1 = m_id_to_name.get(e1)
                name2 = m_id_to_name.get(e2)
                if name1 in trade_counts:
                    trade_counts[name1] += 1
                if name2 in trade_counts:
                    trade_counts[name2] += 1

    trades_list = [{"Manager": m_name, "Completed Trades Involved": count} for m_name, count in trade_counts.items()]
    df_trades = pd.DataFrame(trades_list)
    if not df_trades.empty:
        df_trades.sort_values(by="Completed Trades Involved", ascending=False, inplace=True)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No completed trade data available.")

    # Sub-section 6.3: Most Transferred Players
    st.markdown("#### 📊 Most Transferred Players (In & Out)")
    player_summary = []
    for p_id, counts in m_player_counts.items():
        info = (player_map or {}).get(p_id, {"web_name": f"Player {p_id}", "team": "-", "position": "-"})
        times_in = counts["in"]
        times_out = counts["out"]
        total_activity = times_in + times_out
        net_movement = times_in - times_out

        player_summary.append({
            "Player": info["web_name"],
            "Club": info["team"],
            "Pos": info["position"],
            "Times Brought IN": times_in,
            "Times Dropped OUT": times_out,
            "Total Transactions": total_activity,
            "Net Movement (+/-)": f"+{net_movement}" if net_movement > 0 else str(net_movement),
        })

    df_transferred_players = pd.DataFrame(player_summary)
    if not df_transferred_players.empty:
        df_transferred_players.sort_values(by=["Total Transactions", "Times Brought IN"], ascending=[False, False], inplace=True)
        st.dataframe(df_transferred_players, use_container_width=True, hide_index=True)
    else:
        st.info("No player transfers recorded yet this season.")

    # Sub-section 6.4: Detailed Transaction Log
    st.markdown("#### 📜 Detailed Roster Move & Gameweek Points Impact Log")
    df_log = pd.DataFrame(m_transfer_log)
    if not df_log.empty:
        all_managers = ["All Managers"] + sorted(list(df_log["Manager"].unique()))
        selected_mgr = st.selectbox("Filter moves by Manager:", all_managers, key="tx_log_mgr_filter")

        if selected_mgr != "All Managers":
            df_display_log = df_log[df_log["Manager"] == selected_mgr]
        else:
            df_display_log = df_log

        st.dataframe(df_display_log, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("No transaction history available yet.")

    # Sub-section 6.5: Manager Gameweek Transfer Points Leaderboard
    st.markdown("#### 🏆 Manager Gameweek Transfer Points Leaderboard")
    st.caption("Ranks managers by points scored by incoming transfer players for a selected Gameweek and across the entire season.")

    sorted_gws = sorted(list(m_all_active_gws))

    if sorted_gws:
        selected_gw_choice = st.selectbox(
            "Select Gameweek to Inspect:",
            [f"Gameweek {g}" for g in sorted_gws],
            index=len(sorted_gws) - 1,
            key=f"market_gw_selector_{market_league_choice}"
        )
        selected_gw_num = int(selected_gw_choice.replace("Gameweek ", ""))

        gw_leaderboard_rows = []
        for m_name in m_manager_names:
            gw_pts = m_manager_gw_pts_in.get(m_name, {}).get(selected_gw_num, 0)
            total_pts_all_gws = sum(m_manager_gw_pts_in.get(m_name, {}).values())

            gw_leaderboard_rows.append({
                "Manager": m_name,
                f"GW {selected_gw_num} Points In": gw_pts,
                "Total Transfer Points": total_pts_all_gws,
            })

        df_gw_leaderboard = pd.DataFrame(gw_leaderboard_rows)

        if not df_gw_leaderboard.empty:
            df_gw_leaderboard.sort_values(by="Total Transfer Points", ascending=False, inplace=True)
            df_gw_leaderboard.reset_index(drop=True, inplace=True)
            df_gw_leaderboard.insert(0, "Rank", range(1, len(df_gw_leaderboard) + 1))
            st.dataframe(df_gw_leaderboard, use_container_width=True, hide_index=True)
        else:
            st.info("No leaderboard data available.")
    else:
        st.info("Gameweek transfer leaderboard will populate as Gameweeks finish.")

else:
    st.error("Failed to load Market Tracker data from FPL Draft API.")    positions_map = {}
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


@st.cache_data(ttl=180)
def fetch_league_element_ownership(entries, current_gw):
    """Scrapes the most recent roster picks for each manager in both leagues."""
    prem_owners = {}
    champ_owners = {}
    target_gw = max(1, current_gw or 1)

    for entry in entries:
        entry_id = entry.get("entry_id")
        if not entry_id:
            continue

        l_id = entry.get("league_id")
        mgr_name = entry.get("manager_name") or entry.get("team_name")

        roster_data = fetch_json(ENTRY_BASE_URL.format(entry_id, target_gw))
        if (not roster_data or "picks" not in roster_data) and target_gw > 1:
            roster_data = fetch_json(ENTRY_BASE_URL.format(entry_id, target_gw - 1))

        if roster_data and isinstance(roster_data, dict):
            for pick in roster_data.get("picks", []):
                p_id = pick.get("element")
                if p_id:
                    if l_id == PREMIER_LEAGUE_ID:
                        prem_owners[p_id] = mgr_name
                    elif l_id == CHAMPIONSHIP_LEAGUE_ID:
                        champ_owners[p_id] = mgr_name

    return prem_owners, champ_owners


def parse_standings(league_data):
    """Processes standings dataframe from league details."""
    if not league_data or not isinstance(league_data, dict):
        return pd.DataFrame()

    entries = league_data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries
        if isinstance(e, dict)
    }

    matches_raw = league_data.get("matches", [])
    entry_played_count = {e.get("id"): 0 for e in entries if isinstance(e, dict)}
    for m in matches_raw:
        if isinstance(m, dict) and (m.get("started") or m.get("finished")):
            e1 = m.get("league_entry_1")
            e2 = m.get("league_entry_2")
            if e1 in entry_played_count:
                entry_played_count[e1] += 1
            if e2 in entry_played_count:
                entry_played_count[e2] += 1

    standings_raw = league_data.get("standings", [])
    standings_rows = []

    for s in standings_raw:
        if not isinstance(s, dict):
            continue

        e_id = s.get("league_entry")
        team_display = entry_map.get(e_id, f"Team {e_id}")

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
    return df_standings


def parse_fixtures(league_data):
    """Processes fixtures and scores list from league details."""
    if not league_data or not isinstance(league_data, dict):
        return pd.DataFrame(), None

    entries = league_data.get("league_entries", [])
    entry_map = {
        e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
        for e in entries
        if isinstance(e, dict)
    }

    current_gw = league_data.get("league", {}).get("current_event")
    matches_raw = league_data.get("matches", [])
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
            "Status": status,
        })

    df_fixtures = pd.DataFrame(fixtures_list)
    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)

    return df_fixtures, current_gw


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
                pos_order = p.get("position", 1)
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
prem_data = fetch_json(LEAGUE_URL_FMT.format(PREMIER_LEAGUE_ID))
all_entries = get_all_league_entries()

# Determine active gameweek
detected_active_gw = (
    (prem_data and prem_data.get("league", {}).get("current_event"))
    or (champ_data and champ_data.get("league", {}).get("current_event"))
    or bootstrap_gw
    or 1
)

prem_owners, champ_owners = fetch_league_element_ownership(all_entries, detected_active_gw)

# ==========================================================
# 1. 🏆 CRAFT AND DRAFT LEAGUE STANDINGS
# ==========================================================
st.subheader("🏆 Craft and Draft League Standings")

standings_league_choice = st.radio(
    "Select League Standings:",
    ["Premier Standings", "Championship Standings"],
    horizontal=True,
    key="standings_selector",
)

selected_standings_data = prem_data if standings_league_choice == "Premier Standings" else champ_data
df_standings = parse_standings(selected_standings_data)

if not df_standings.empty:
    st.dataframe(df_standings, use_container_width=True, hide_index=True)
else:
    st.info("Standings will appear once matches have commenced.")

st.divider()

# ==========================================================
# 2. 📅 CRAFT AND DRAFT FIXTURES & SCORES
# ==========================================================
fixtures_league_choice = st.radio(
    "Select League Fixtures:",
    ["Premier Fixtures", "Championship Fixtures"],
    horizontal=True,
    key="fixtures_selector",
)

st.subheader(f"📅 {fixtures_league_choice} & Scores")

selected_fixtures_data = prem_data if fixtures_league_choice == "Premier Fixtures" else champ_data
df_fixtures, detected_gw = parse_fixtures(selected_fixtures_data)
active_gw = detected_gw or bootstrap_gw or 1

if not df_fixtures.empty:
    unique_gws = sorted([int(g) for g in df_fixtures["GW"].dropna().unique()])
    gw_options = [f"Gameweek {g}" for g in unique_gws] + ["All Gameweeks"]

    target_label = f"Gameweek {active_gw}"
    default_idx = gw_options.index(target_label) if target_label in gw_options else 0

    selected_option = st.selectbox(
        "Select Gameweek:",
        gw_options,
        index=default_idx,
        key=f"gw_select_{fixtures_league_choice}",
    )

    if selected_option == "All Gameweeks":
        df_display = df_fixtures
    else:
        selected_gw_num = int(selected_option.replace("Gameweek ", ""))
        df_display = df_fixtures[df_fixtures["GW"] == selected_gw_num]

    st.caption(f"Showing live fixtures for **{selected_option}**")
    st.dataframe(df_display, use_container_width=True, hide_index=True, height=350)
else:
    st.info("No fixtures found.")

st.divider()

# ==========================================================
# 3. ⚽ PREMIER LEAGUE PLAYER POOL PERFORMANCE
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
            "C&D Premier Owner": prem_owners.get(p_id, "Free Agent"),
            "C&D Championship Owner": champ_owners.get(p_id, "Free Agent"),
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

st.divider()

# ==========================================================
# 4. 🧠 MANAGER LINEUP SELECTION & SQUAD USAGE
# ==========================================================
st.subheader("🧠 Manager Lineup Selection & Squad Usage")
st.caption("Analyzes starting lineup optimization vs points left on the bench.")

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
# 5. 🔄 WAIVER & TRADE MARKET TRACKER
# ==========================================================
st.subheader("🔄 Waiver & Trade Market Tracker")

market_league_choice = st.radio(
    "Select League for Market Tracker:",
    ["C&D Premier", "C&D Championship"],
    horizontal=True,
    key="market_league_selector",
)

active_market_league_id = PREMIER_LEAGUE_ID if market_league_choice == "C&D Premier" else CHAMPIONSHIP_LEAGUE_ID
active_market_league_data = prem_data if market_league_choice == "C&D Premier" else champ_data

tx_data = fetch_json(TX_URL_FMT.format(active_market_league_id))
trades_data = fetch_json(TRADES_URL_FMT.format(active_market_league_id))

if active_market_league_data and isinstance(active_market_league_data, dict):
    m_entries = active_market_league_data.get("league_entries", [])
    m_id_to_name = {}
    m_manager_names = []

    for e in m_entries:
        if isinstance(e, dict):
            name = f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
            m_manager_names.append(name)
            if "id" in e:
                m_id_to_name[e["id"]] = name
            if "entry_id" in e:
                m_id_to_name[e["entry_id"]] = name

    # Transaction & Point Calculations
    m_player_counts = {}
    m_transfer_log = []
    m_gw_scores_cache = {}

    m_manager_stats = {
        m_name: {
            "waiver_att": 0,
            "waiver_succ": 0,
            "fa_succ": 0,
            "pts_in": 0,
            "pts_out": 0,
            "gws": set(),
        }
        for m_name in m_manager_names
    }

    m_manager_gw_pts_in = {m_name: {} for m_name in m_manager_names}
    m_all_active_gws = set()

    if tx_data and isinstance(tx_data, dict):
        transactions = tx_data.get("transactions", [])

        for tx in transactions:
            if not isinstance(tx, dict):
                continue

            raw_id = tx.get("entry") or tx.get("league_entry")
            m_name = m_id_to_name.get(raw_id)
            kind = tx.get("kind")  # 'w' = waiver, 'f' = free agency
            result = tx.get("result")  # 'a' = accepted
            gw = tx.get("event")
            is_successful = (result == "a") or (kind == "f")

            if m_name and m_name in m_manager_stats:
                if gw:
                    m_manager_stats[m_name]["gws"].add(gw)

                if kind == "w":
                    m_manager_stats[m_name]["waiver_att"] += 1
                    if result == "a":
                        m_manager_stats[m_name]["waiver_succ"] += 1
                elif kind == "f":
                    m_manager_stats[m_name]["fa_succ"] += 1

            if is_successful and gw:
                m_all_active_gws.add(gw)
                el_in = tx.get("element_in")
                el_out = tx.get("element_out")
                move_type = "Waiver" if kind == "w" else "Free Agency"

                if gw not in m_gw_scores_cache:
                    m_gw_scores_cache[gw] = fetch_gw_live_scores(gw)
                current_gw_scores = m_gw_scores_cache[gw]

                in_pts = current_gw_scores.get(el_in, 0) if el_in else 0
                out_pts = current_gw_scores.get(el_out, 0) if el_out else 0
                net_pts = in_pts - out_pts

                if m_name and m_name in m_manager_stats:
                    m_manager_stats[m_name]["pts_in"] += in_pts
                    m_manager_stats[m_name]["pts_out"] += out_pts
                    m_manager_gw_pts_in[m_name][gw] = m_manager_gw_pts_in[m_name].get(gw, 0) + in_pts

                if el_in:
                    if el_in not in m_player_counts:
                        m_player_counts[el_in] = {"in": 0, "out": 0}
                    m_player_counts[el_in]["in"] += 1

                if el_out:
                    if el_out not in m_player_counts:
                        m_player_counts[el_out] = {"in": 0, "out": 0}
                    m_player_counts[el_out]["out"] += 1

                if out_pts > 0:
                    tx_pct = round(((in_pts - out_pts) / out_pts) * 100, 1)
                    tx_pct_str = f"+{tx_pct}%" if tx_pct > 0 else f"{tx_pct}%"
                elif in_pts > 0:
                    tx_pct_str = "+100% (Pure Gain)"
                else:
                    tx_pct_str = "0.0%"

                p_in_info = (player_map or {}).get(el_in, {"web_name": f"Player {el_in}", "team": "-", "position": "-"})
                p_out_info = (player_map or {}).get(el_out, {"web_name": f"Player {el_out}", "team": "-", "position": "-"})

                m_transfer_log.append({
                    "Gameweek": f"GW {gw}",
                    "Manager": m_name or f"Manager ({raw_id})",
                    "Type": move_type,
                    "Player In": f"{p_in_info['web_name']} ({p_in_info['team']})",
                    "Pts In": in_pts,
                    "Player Out": f"{p_out_info['web_name']} ({p_out_info['team']})",
                    "Pts Out": out_pts,
                    "Net Pts": f"+{net_pts}" if net_pts > 0 else str(net_pts),
                    "Transfer ROI": tx_pct_str,
                })

    # Sub-section 5.1: Manager Waiver Activity & ROI Table
    st.markdown("#### 📈 Manager Waiver Activity & Net Points Impact")
    tx_list = []
    for m_name, stats in m_manager_stats.items():
        att = stats["waiver_att"]
        succ = stats["waiver_succ"]
        fa = stats["fa_succ"]
        total_changes = succ + fa
        rate = round((succ / att) * 100, 1) if att > 0 else 0.0
        p_in = stats["pts_in"]
        p_out = stats["pts_out"]
        net_diff = p_in - p_out

        if p_out > 0:
            imp_pct = round(((p_in - p_out) / p_out) * 100, 1)
            imp_pct_str = f"+{imp_pct}%" if imp_pct > 0 else f"{imp_pct}%"
        elif p_in > 0:
            imp_pct_str = "+100.0%"
        else:
            imp_pct_str = "0.0%"

        tx_list.append({
            "Manager": m_name,
            "Total Successful Changes": total_changes,
            "Pts from Players IN": p_in,
            "Pts from Players OUT": p_out,
            "Net Points Diff": f"+{net_diff}" if net_diff > 0 else str(net_diff),
            "Overall ROI (%)": imp_pct_str,
            "Waivers Won": succ,
            "Free Agent Pickups": fa,
            "Waiver Success Rate": f"{rate}%",
            "Active GWs": len(stats["gws"]),
        })

    df_tx = pd.DataFrame(tx_list)
    if not df_tx.empty:
        df_tx["sort_net"] = df_tx["Net Points Diff"].astype(int)
        df_tx.sort_values(by=["sort_net", "Total Successful Changes"], ascending=[False, False], inplace=True)
        df_tx.drop(columns=["sort_net"], inplace=True)
        st.dataframe(df_tx, use_container_width=True, hide_index=True)
    else:
        st.info("No transaction stats recorded.")

    # Sub-section 5.2: Manager-to-Manager Trades Tracker
    st.markdown("#### 🤝 Manager-to-Manager Trades Tracker")
    trade_counts = {m_name: 0 for m_name in m_manager_names}
    if trades_data and isinstance(trades_data, dict):
        trades = trades_data.get("trades", [])
        for t in trades:
            if isinstance(t, dict) and t.get("state") == "p":
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                name1 = m_id_to_name.get(e1)
                name2 = m_id_to_name.get(e2)
                if name1 in trade_counts:
                    trade_counts[name1] += 1
                if name2 in trade_counts:
                    trade_counts[name2] += 1

    trades_list = [{"Manager": m_name, "Completed Trades Involved": count} for m_name, count in trade_counts.items()]
    df_trades = pd.DataFrame(trades_list)
    if not df_trades.empty:
        df_trades.sort_values(by="Completed Trades Involved", ascending=False, inplace=True)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No completed trade data available.")

    # Sub-section 5.3: Most Transferred Players
    st.markdown("#### 📊 Most Transferred Players (In & Out)")
    player_summary = []
    for p_id, counts in m_player_counts.items():
        info = (player_map or {}).get(p_id, {"web_name": f"Player {p_id}", "team": "-", "position": "-"})
        times_in = counts["in"]
        times_out = counts["out"]
        total_activity = times_in + times_out
        net_movement = times_in - times_out

        player_summary.append({
            "Player": info["web_name"],
            "Club": info["team"],
            "Pos": info["position"],
            "Times Brought IN": times_in,
            "Times Dropped OUT": times_out,
            "Total Transactions": total_activity,
            "Net Movement (+/-)": f"+{net_movement}" if net_movement > 0 else str(net_movement),
        })

    df_transferred_players = pd.DataFrame(player_summary)
    if not df_transferred_players.empty:
        df_transferred_players.sort_values(by=["Total Transactions", "Times Brought IN"], ascending=[False, False], inplace=True)
        st.dataframe(df_transferred_players, use_container_width=True, hide_index=True)
    else:
        st.info("No player transfers recorded yet this season.")

    # Sub-section 5.4: Detailed Transaction Log
    st.markdown("#### 📜 Detailed Roster Move & Gameweek Points Impact Log")
    df_log = pd.DataFrame(m_transfer_log)
    if not df_log.empty:
        all_managers = ["All Managers"] + sorted(list(df_log["Manager"].unique()))
        selected_mgr = st.selectbox("Filter moves by Manager:", all_managers, key="tx_log_mgr_filter")

        if selected_mgr != "All Managers":
            df_display_log = df_log[df_log["Manager"] == selected_mgr]
        else:
            df_display_log = df_log

        st.dataframe(df_display_log, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("No transaction history available yet.")

    # Sub-section 5.5: Manager Gameweek Transfer Points Leaderboard (Single GW Dropdown + Total)
    st.markdown("#### 🏆 Manager Gameweek Transfer Points Leaderboard")
    st.caption("Ranks managers by points scored by incoming transfer players for a selected Gameweek and across the entire season.")

    sorted_gws = sorted(list(m_all_active_gws))

    if sorted_gws:
        # Gameweek dropdown with the latest Gameweek selected by default
        selected_gw_choice = st.selectbox(
            "Select Gameweek to Inspect:",
            [f"Gameweek {g}" for g in sorted_gws],
            index=len(sorted_gws) - 1,
            key=f"market_gw_selector_{market_league_choice}"
        )
        selected_gw_num = int(selected_gw_choice.replace("Gameweek ", ""))

        gw_leaderboard_rows = []
        for m_name in m_manager_names:
            gw_pts = m_manager_gw_pts_in.get(m_name, {}).get(selected_gw_num, 0)
            total_pts_all_gws = sum(m_manager_gw_pts_in.get(m_name, {}).values())

            gw_leaderboard_rows.append({
                "Manager": m_name,
                f"GW {selected_gw_num} Points In": gw_pts,
                "Total Transfer Points": total_pts_all_gws,
            })

        df_gw_leaderboard = pd.DataFrame(gw_leaderboard_rows)

        if not df_gw_leaderboard.empty:
            df_gw_leaderboard.sort_values(by="Total Transfer Points", ascending=False, inplace=True)
            df_gw_leaderboard.reset_index(drop=True, inplace=True)
            df_gw_leaderboard.insert(0, "Rank", range(1, len(df_gw_leaderboard) + 1))
            st.dataframe(df_gw_leaderboard, use_container_width=True, hide_index=True)
        else:
            st.info("No leaderboard data available.")
    else:
        st.info("Gameweek transfer leaderboard will populate as Gameweeks finish.")

else:
    st.error("Failed to load Market Tracker data from FPL Draft API.")
