import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
# Use standard centered container for natural mobile scaling
st.set_page_config(page_title="Craft & Draft Squad & Player Analytics", layout="wide")

# Auto-refresh every 60 seconds
st_autorefresh(interval=60000, key="cnd_player_analysis_refresh")

# --- Mobile Responsive CSS Styling ---
st.markdown("""
<style>
    /* Reduce global outer margins on mobile phones */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }
        /* Make dataframes occupy 100% viewport width without overflowing */
        [data-testid="stDataFrame"] {
            width: 100% !important;
        }
        /* Adjust font size inside dataframe tables */
        div[data-testid="stDataFrame"] div {
            font-size: 0.82rem !important;
        }
        /* Make radio buttons wrap cleanly on small screens */
        div[role="radiogroup"] {
            gap: 0.3rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

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
    """Processes standings dataframe optimized for mobile screen width."""
    if not league_data or not isinstance(league_data, dict):
        return pd.DataFrame()

    entries = league_data.get("league_entries", [])
    entry_map = {
        e.get("id"): e.get("entry_name", "Team")
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

        # Compact columns so table fits within 360-400px mobile widths
        standings_rows.append({
            "R": s.get("rank", "-"),
            "Team": team_display,
            "P": actual_played,
            "W-D-L": f"{won}-{drawn}-{lost}",
            "+/-": f"{s.get('points_for', 0)}/{s.get('points_against', 0)}",
            "Pts": s.get("total", 0),
        })

    df_standings = pd.DataFrame(standings_rows)
    if not df_standings.empty:
        df_standings.sort_values(by=["R"], inplace=True)
    return df_standings


def get_blooper_standings(prem_data, champ_data):
    """Calculates live total points across both leagues, ranking lowest to highest in mobile width."""
    player_stats = []
    datasets = [prem_data, champ_data]

    for data in datasets:
        if not data or not isinstance(data, dict):
            continue

        entries = data.get("league_entries", [])
        matches = data.get("matches", [])

        entry_map = {}
        live_points = {}

        for e in entries:
            if isinstance(e, dict):
                e_id = e.get("id")
                entry_map[e_id] = {
                    "name": f"{e.get('player_first_name', '')} {e.get('player_last_name', '')[:1]}.".strip(),
                    "team": e.get("entry_name", "Team"),
                }
                live_points[e_id] = 0

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

        for e_id, info in entry_map.items():
            player_stats.append({
                "Player": info["name"],
                "Team": info["team"],
                "Pts": live_points.get(e_id, 0),
            })

    if len(player_stats) < 16:
        for p in range(len(player_stats) + 1, 17):
            player_stats.append({
                "Player": f"Player {p}",
                "Team": f"Team {p}",
                "Pts": 0,
            })

    df = pd.DataFrame(player_stats)
    if df.empty:
        return df

    df.sort_values(by=["Pts", "Player"], ascending=[True, True], inplace=True)
    df.reset_index(drop=True, inplace=True)

    ranked_rows = []
    total_players = len(df)

    for idx, row in df.iterrows():
        rank_num = idx + 1
        rank_str = "💩 1" if rank_num == 1 else (f"⭐ {rank_num}" if rank_num == total_players else str(rank_num))
        ranked_rows.append({
            "R": rank_str,
            "Player": row["Player"],
            "Team": row["Team"],
            "Total Pts": row["Pts"],
        })

    return pd.DataFrame(ranked_rows)


def calculate_manager_of_the_year(prem_data, champ_data):
    """Calculates MOTY award winners in a mobile-optimized compact view."""
    leagues_payload = [
        ("Prem", prem_data),
        ("Champ", champ_data),
    ]

    manager_records = {}
    gw_scores = {}

    for l_label, l_data in leagues_payload:
        if not l_data or not isinstance(l_data, dict):
            continue

        entries = l_data.get("league_entries", [])
        entry_meta = {}
        for e in entries:
            if isinstance(e, dict):
                e_id = e.get("id")
                disp = f"{e.get('player_first_name', '')} {e.get('player_last_name', '')[:1]}.".strip()
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

        for m in l_data.get("matches", []):
            if not isinstance(m, dict) or not m.get("finished"):
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
                gw_scores[gw].append({"mgr_key": (l_label, e1), "score": s1})
                manager_records[(l_label, e1)]["total_points_scored"] += s1

            if e2 in entry_meta:
                gw_scores[gw].append({"mgr_key": (l_label, e2), "score": s2})
                manager_records[(l_label, e2)]["total_points_scored"] += s2

    for gw, score_list in sorted(gw_scores.items()):
        if not score_list:
            continue
        max_score = max(item["score"] for item in score_list)
        if max_score > 0:
            winners = [item["mgr_key"] for item in score_list if item["score"] == max_score]
            for w_key in winners:
                if w_key in manager_records:
                    manager_records[w_key]["motw_awards"] += 1
                    manager_records[w_key]["gws_won"].append(str(gw))

    rows = []
    for info in manager_records.values():
        gws_won_str = ",".join(info["gws_won"]) if info["gws_won"] else "-"
        rows.append({
            "Lge": info["League"],
            "Manager": info["Manager"],
            "Awards": info["motw_awards"],
            "Total Pts": info["total_points_scored"],
            "GWs Won": gws_won_str,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(by=["Awards", "Total Pts"], ascending=[False, False], inplace=True)
        df.reset_index(drop=True, inplace=True)
        df.insert(0, "R", range(1, len(df) + 1))
    return df


def parse_fixtures(league_data):
    """Processes compact fixtures dataframe for mobile widths."""
    if not league_data or not isinstance(league_data, dict):
        return pd.DataFrame(), None

    entries = league_data.get("league_entries", [])
    entry_map = {
        e.get("id"): e.get("entry_name", "Team")
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

        status = "FT" if is_finished else ("LIVE" if is_started else "SCHED")
        h_score = m.get("league_entry_1_points", 0) if (is_started or is_finished) else "-"
        a_score = m.get("league_entry_2_points", 0) if (is_started or is_finished) else "-"

        fixtures_list.append({
            "GW": gw,
            "Home Team": entry_map.get(m.get("league_entry_1"), f"E{m.get('league_entry_1')}"),
            "Score": f"{h_score} - {a_score}",
            "Away Team": entry_map.get(m.get("league_entry_2"), f"E{m.get('league_entry_2')}"),
            "Status": status,
        })

    df_fixtures = pd.DataFrame(fixtures_list)
    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)

    return df_fixtures, current_gw


def get_manager_lineup_df(entry_id, gw, player_map, live_scores):
    """Fetches manager lineup and formats into Starters and Bench DataFrames."""
    if not entry_id:
        return pd.DataFrame(), pd.DataFrame(), 0

    gw_data = fetch_json(ENTRY_BASE_URL.format(entry_id, gw))
    if not gw_data or not isinstance(gw_data, dict):
        return pd.DataFrame(), pd.DataFrame(), 0

    picks = gw_data.get("picks", [])
    starters = []
    bench = []
    total_starters_pts = 0

    for p in picks:
        if not isinstance(p, dict):
            continue
        p_id = p.get("element")
        order = p.get("position", 1)
        info = player_map.get(p_id, {"web_name": f"P{p_id}", "position": "-", "team": "-"})
        gw_pts = live_scores.get(p_id, 0)

        record = {
            "Pos": info.get("position", "-"),
            "Player": f"{info.get('web_name')} ({info.get('team')})",
            "Pts": gw_pts,
        }

        if order <= 11:
            starters.append(record)
            total_starters_pts += gw_pts
        else:
            bench.append(record)

    df_starters = pd.DataFrame(starters)
    df_bench = pd.DataFrame(bench)
    return df_starters, df_bench, total_starters_pts


def analyze_squad_usage(entries, player_map, finished_gws):
    """Parses each manager's lineup usage in a compact format."""
    squad_stats = []

    for entry in entries:
        entry_id = entry["entry_id"]
        if not entry_id:
            continue

        started_points = 0
        benched_points = 0
        recent_gws = finished_gws[-5:] if len(finished_gws) > 5 else finished_gws

        for gw in recent_gws:
            gw_data = fetch_json(ENTRY_BASE_URL.format(entry_id, gw))
            if not gw_data or not isinstance(gw_data, dict):
                continue

            for p in gw_data.get("picks", []):
                if not isinstance(p, dict):
                    continue
                p_id = p.get("element")
                pos_order = p.get("position", 1)
                p_info = player_map.get(p_id, {})
                approx_pts = p_info.get("total_points", 0) / max(len(finished_gws), 1)

                if pos_order <= 11:
                    started_points += approx_pts
                else:
                    benched_points += approx_pts

        total_pts = started_points + benched_points
        bench_efficiency = round((started_points / total_pts) * 100, 1) if total_pts > 0 else 100.0

        squad_stats.append({
            "Team": entry["team_name"],
            "Start Pts": round(started_points, 1),
            "Bench Pts": round(benched_points, 1),
            "Eff (%)": f"{bench_efficiency}%",
        })

    return pd.DataFrame(squad_stats)


# --- Load Core Data ---
player_map, pos_map, team_map, finished_gws, bootstrap_gw = load_bootstrap_data()
champ_data = fetch_json(LEAGUE_URL_FMT.format(CHAMPIONSHIP_LEAGUE_ID))
prem_data = fetch_json(LEAGUE_URL_FMT.format(PREMIER_LEAGUE_ID))
all_entries = get_all_league_entries()

detected_active_gw = (
    (prem_data and prem_data.get("league", {}).get("current_event"))
    or (champ_data and champ_data.get("league", {}).get("current_event"))
    or bootstrap_gw
    or 1
)

prem_owners, champ_owners = fetch_league_element_ownership(all_entries, detected_active_gw)

# ==========================================================
# 1. 🏆 CRAFT AND DRAFT LEAGUE TABLES
# ==========================================================
st.subheader("🏆 Craft and Draft League Tables")

standings_league_choice = st.radio(
    "Select League Table:",
    [
        "Premier Standings",
        "Championship Standings",
        "Blooper League Standings",
        "Manager of the Year",
    ],
    horizontal=True,
    key="standings_selector",
)

if standings_league_choice == "Premier Standings":
    df_standings = parse_standings(prem_data)
    if not df_standings.empty:
        st.dataframe(df_standings, use_container_width=True, hide_index=True)
    else:
        st.info("Standings will appear once matches have commenced.")

elif standings_league_choice == "Championship Standings":
    df_standings = parse_standings(champ_data)
    if not df_standings.empty:
        st.dataframe(df_standings, use_container_width=True, hide_index=True)
    else:
        st.info("Standings will appear once matches have commenced.")

elif standings_league_choice == "Blooper League Standings":
    st.caption("Lowest point scorers rank highest.")
    df_blooper = get_blooper_standings(prem_data, champ_data)
    if not df_blooper.empty:
        st.dataframe(df_blooper, use_container_width=True, hide_index=True)
    else:
        st.info("Blooper standings will appear once matches have commenced.")

elif standings_league_choice == "Manager of the Year":
    st.caption("1 point awarded per completed GW to highest match score across both leagues.")
    df_moty = calculate_manager_of_the_year(prem_data, champ_data)
    if not df_moty.empty:
        st.dataframe(df_moty, use_container_width=True, hide_index=True)
    else:
        st.info("Manager of the Year awards will be calculated as Gameweeks finish.")

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

    st.dataframe(df_display, use_container_width=True, hide_index=True, height=260)
else:
    st.info("No fixtures found.")

# ==========================================================
# 2B. ⚔️ HEAD-TO-HEAD FIXTURE LINEUPS (SIDE-BY-SIDE)
# ==========================================================
st.markdown("#### ⚔️ Fixture Lineup Breakdown")

if selected_fixtures_data and isinstance(selected_fixtures_data, dict):
    h2h_entries = selected_fixtures_data.get("league_entries", [])
    entry_lookup = {}
    for e in h2h_entries:
        if isinstance(e, dict):
            e_id = e.get("id")
            team_name = e.get("entry_name", "Team")
            mgr = f"{e.get('player_first_name', '')} {e.get('player_last_name', '')[:1]}.".strip()
            entry_lookup[e_id] = {
                "display": f"{team_name} ({mgr})",
                "entry_id": e.get("entry_id"),
            }

    h2h_matches = selected_fixtures_data.get("matches", [])
    all_gw_nums = sorted(list({m.get("event") for m in h2h_matches if isinstance(m, dict) and m.get("event")}))

    if all_gw_nums:
        col_gw_drop, col_fix_drop = st.columns(2)

        default_gw_idx = all_gw_nums.index(active_gw) if active_gw in all_gw_nums else len(all_gw_nums) - 1
        with col_gw_drop:
            chosen_h2h_gw = st.selectbox(
                "1. Select GW:",
                all_gw_nums,
                index=default_gw_idx,
                format_func=lambda g: f"GW {g}",
                key=f"h2h_gw_drop_{fixtures_league_choice}",
            )

        gw_matches = [m for m in h2h_matches if isinstance(m, dict) and m.get("event") == chosen_h2h_gw]

        fixture_options = {}
        for idx, m in enumerate(gw_matches):
            e1 = m.get("league_entry_1")
            e2 = m.get("league_entry_2")
            t1_name = entry_lookup.get(e1, {}).get("display", f"Entry {e1}")
            t2_name = entry_lookup.get(e2, {}).get("display", f"Entry {e2}")
            label = f"F{idx + 1}: {t1_name} vs {t2_name}"
            fixture_options[label] = m

        with col_fix_drop:
            chosen_fixture_label = st.selectbox(
                "2. Select Match:",
                list(fixture_options.keys()),
                key=f"h2h_fix_drop_{fixtures_league_choice}",
            )

        chosen_match = fixture_options.get(chosen_fixture_label)

        if chosen_match:
            e1_id = chosen_match.get("league_entry_1")
            e2_id = chosen_match.get("league_entry_2")

            real_entry1 = entry_lookup.get(e1_id, {}).get("entry_id")
            real_entry2 = entry_lookup.get(e2_id, {}).get("entry_id")

            team1_label = entry_lookup.get(e1_id, {}).get("display", "Team 1")
            team2_label = entry_lookup.get(e2_id, {}).get("display", "Team 2")

            gw_scores = fetch_gw_live_scores(chosen_h2h_gw)

            with st.spinner("Loading rosters..."):
                t1_starters, t1_bench, t1_pts = get_manager_lineup_df(real_entry1, chosen_h2h_gw, player_map, gw_scores)
                t2_starters, t2_bench, t2_pts = get_manager_lineup_df(real_entry2, chosen_h2h_gw, player_map, gw_scores)

            score_diff = t1_pts - t2_pts
            diff_text = f"+{score_diff}" if score_diff > 0 else f"{score_diff}"
            st.info(f"**{team1_label}** ({t1_pts}) vs **{team2_label}** ({t2_pts}) | Margin: **{diff_text}**")

            # Stack sequentially on mobile or use tight columns
            col_t1, col_t2 = st.columns(2)

            with col_t1:
                st.markdown(f"**🏠 {team1_label}**")
                st.caption(f"Starters ({t1_pts} pts)")
                if not t1_starters.empty:
                    st.dataframe(t1_starters, use_container_width=True, hide_index=True)
                st.caption("Bench")
                if not t1_bench.empty:
                    st.dataframe(t1_bench, use_container_width=True, hide_index=True)

            with col_t2:
                st.markdown(f"**🚗 {team2_label}**")
                st.caption(f"Starters ({t2_pts} pts)")
                if not t2_starters.empty:
                    st.dataframe(t2_starters, use_container_width=True, hide_index=True)
                st.caption("Bench")
                if not t2_bench.empty:
                    st.dataframe(t2_bench, use_container_width=True, hide_index=True)
    else:
        st.info("No fixtures scheduled yet.")

st.divider()

# ==========================================================
# 3. ⚽ PREMIER LEAGUE PLAYER POOL PERFORMANCE
# ==========================================================
st.subheader("⚽ Player Pool Performance")

if player_map:
    player_records = []
    for p_id, p_info in player_map.items():
        # Compact strings for mobile view
        player_records.append({
            "Player": f"{p_info['web_name']} ({p_info['team']})",
            "Pos": p_info["position"],
            "Pts": p_info["total_points"],
            "Prem": prem_owners.get(p_id, "-")[:12],
            "Champ": champ_owners.get(p_id, "-")[:12],
            "G": p_info["goals"],
            "A": p_info["assists"],
        })

    df_players = pd.DataFrame(player_records)

    c1, c2, c3 = st.columns(3)
    pos_filter = c1.selectbox("Position:", ["All"] + sorted(list(pos_map.values())))
    club_filter = c2.selectbox("Club:", ["All"] + sorted(list(team_map.values())))
    min_points = c3.slider("Min Pts:", 0, 250, 0)

    df_filtered_players = df_players.copy()
    if pos_filter != "All":
        df_filtered_players = df_filtered_players[df_filtered_players["Pos"] == pos_filter]
    if club_filter != "All":
        df_filtered_players = df_filtered_players[df_filtered_players["Player"].str.contains(f"({club_filter})", regex=False)]
    df_filtered_players = df_filtered_players[df_filtered_players["Pts"] >= min_points]

    df_filtered_players.sort_values(by="Pts", ascending=False, inplace=True)
    st.dataframe(df_filtered_players, use_container_width=True, hide_index=True, height=350)
else:
    st.info("Player data could not be loaded.")

st.divider()

# ==========================================================
# 4. 🧠 MANAGER LINEUP SELECTION & SQUAD USAGE
# ==========================================================
st.subheader("🧠 Squad & Bench Usage")

league_filter = st.radio(
    "Filter League:",
    ["All Combined", "C&D Premier", "C&D Championship"],
    horizontal=True,
)

selected_entries = all_entries
if league_filter == "C&D Premier":
    selected_entries = [e for e in all_entries if e["league_id"] == PREMIER_LEAGUE_ID]
elif league_filter == "C&D Championship":
    selected_entries = [e for e in all_entries if e["league_id"] == CHAMPIONSHIP_LEAGUE_ID]

with st.spinner("Analyzing squad usage..."):
    df_squad_usage = analyze_squad_usage(selected_entries, player_map, finished_gws)

if not df_squad_usage.empty:
    df_squad_usage.sort_values(by="Start Pts", ascending=False, inplace=True)
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
            name = e.get("entry_name", "Team")
            m_manager_names.append(name)
            if "id" in e:
                m_id_to_name[e["id"]] = name
            if "entry_id" in e:
                m_id_to_name[e["entry_id"]] = name

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
            kind = tx.get("kind")
            result = tx.get("result")
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
                move_type = "Waiver" if kind == "w" else "FA"

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

                p_in_info = (player_map or {}).get(el_in, {"web_name": f"P{el_in}", "team": "-", "position": "-"})
                p_out_info = (player_map or {}).get(el_out, {"web_name": f"P{el_out}", "team": "-", "position": "-"})

                m_transfer_log.append({
                    "GW": f"GW{gw}",
                    "Team": m_name or f"E{raw_id}",
                    "In": f"{p_in_info['web_name']} ({in_pts}p)",
                    "Out": f"{p_out_info['web_name']} ({out_pts}p)",
                    "+/-": f"+{net_pts}" if net_pts > 0 else str(net_pts),
                })

    # Sub-section 5.1: Manager Waiver Activity
    st.markdown("#### 📈 Waiver Activity & Net Impact")
    tx_list = []
    for m_name, stats in m_manager_stats.items():
        succ = stats["waiver_succ"]
        fa = stats["fa_succ"]
        p_in = stats["pts_in"]
        p_out = stats["pts_out"]
        net_diff = p_in - p_out

        tx_list.append({
            "Team": m_name,
            "Moves": succ + fa,
            "In Pts": p_in,
            "Out Pts": p_out,
            "Net": f"+{net_diff}" if net_diff > 0 else str(net_diff),
            "W/FA": f"{succ}/{fa}",
        })

    df_tx = pd.DataFrame(tx_list)
    if not df_tx.empty:
        df_tx["sort_net"] = df_tx["Net"].astype(int)
        df_tx.sort_values(by=["sort_net", "Moves"], ascending=[False, False], inplace=True)
        df_tx.drop(columns=["sort_net"], inplace=True)
        st.dataframe(df_tx, use_container_width=True, hide_index=True)
    else:
        st.info("No transaction stats recorded.")

    # Sub-section 5.2: Manager-to-Manager Trades Tracker
    st.markdown("#### 🤝 Manager Trades")
    trade_counts = {m_name: 0 for m_name in m_manager_names}
    if trades_data and isinstance(trades_data, dict):
        for t in trades_data.get("trades", []):
            if isinstance(t, dict) and t.get("state") == "p":
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                name1 = m_id_to_name.get(e1)
                name2 = m_id_to_name.get(e2)
                if name1 in trade_counts:
                    trade_counts[name1] += 1
                if name2 in trade_counts:
                    trade_counts[name2] += 1

    trades_list = [{"Team": m_name, "Completed Trades": count} for m_name, count in trade_counts.items()]
    df_trades = pd.DataFrame(trades_list)
    if not df_trades.empty:
        df_trades.sort_values(by="Completed Trades", ascending=False, inplace=True)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No completed trade data available.")

    # Sub-section 5.3: Most Transferred Players
    st.markdown("#### 📊 Most Transferred Players")
    player_summary = []
    for p_id, counts in m_player_counts.items():
        info = (player_map or {}).get(p_id, {"web_name": f"P{p_id}", "team": "-", "position": "-"})
        times_in = counts["in"]
        times_out = counts["out"]
        net_movement = times_in - times_out

        player_summary.append({
            "Player": f"{info['web_name']} ({info['team']})",
            "In": times_in,
            "Out": times_out,
            "Total": times_in + times_out,
            "Net": f"+{net_movement}" if net_movement > 0 else str(net_movement),
        })

    df_transferred_players = pd.DataFrame(player_summary)
    if not df_transferred_players.empty:
        df_transferred_players.sort_values(by=["Total", "In"], ascending=[False, False], inplace=True)
        st.dataframe(df_transferred_players, use_container_width=True, hide_index=True)
    else:
        st.info("No player transfers recorded yet this season.")

    # Sub-section 5.4: Detailed Transaction Log
    st.markdown("#### 📜 Detailed Transfer Log")
    df_log = pd.DataFrame(m_transfer_log)
    if not df_log.empty:
        all_managers = ["All"] + sorted(list(df_log["Team"].unique()))
        selected_mgr = st.selectbox("Filter Team:", all_managers, key="tx_log_mgr_filter")
        df_display_log = df_log if selected_mgr == "All" else df_log[df_log["Team"] == selected_mgr]
        st.dataframe(df_display_log, use_container_width=True, hide_index=True, height=280)
    else:
        st.info("No transaction history available yet.")

    # Sub-section 5.5: Manager Gameweek Transfer Points Leaderboard
    st.markdown("#### 🏆 Transfer Points Leaderboard")
    sorted_gws = sorted(list(m_all_active_gws))

    if sorted_gws:
        selected_gw_choice = st.selectbox(
            "Inspect GW:",
            [f"Gameweek {g}" for g in sorted_gws],
            index=len(sorted_gws) - 1,
            key=f"market_gw_selector_{market_league_choice}",
        )
        selected_gw_num = int(selected_gw_choice.replace("Gameweek ", ""))

        gw_leaderboard_rows = []
        for m_name in m_manager_names:
            gw_pts = m_manager_gw_pts_in.get(m_name, {}).get(selected_gw_num, 0)
            total_pts_all_gws = sum(m_manager_gw_pts_in.get(m_name, {}).values())

            gw_leaderboard_rows.append({
                "Team": m_name,
                f"GW{selected_gw_num} Pts": gw_pts,
                "Total Pts": total_pts_all_gws,
            })

        df_gw_leaderboard = pd.DataFrame(gw_leaderboard_rows)

        if not df_gw_leaderboard.empty:
            df_gw_leaderboard.sort_values(by="Total Pts", ascending=False, inplace=True)
            df_gw_leaderboard.reset_index(drop=True, inplace=True)
            df_gw_leaderboard.insert(0, "R", range(1, len(df_gw_leaderboard) + 1))
            st.dataframe(df_gw_leaderboard, use_container_width=True, hide_index=True)
        else:
            st.info("No leaderboard data available.")
    else:
        st.info("Gameweek transfer leaderboard will populate as Gameweeks finish.")

else:
    st.error("Failed to load Market Tracker data from FPL Draft API.")
