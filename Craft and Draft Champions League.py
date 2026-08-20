import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Streamlit Page Config ---
st.set_page_config(page_title="Craft & Draft Champions League", layout="wide")
# Set autorefresh to 60s (prevents Streamlit memory crashes)
st_autorefresh(interval=60000, key="cd_cl_refresh")

LEAGUE_1_ID = 858
LEAGUE_2_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"
TX_URL_FMT = "https://draft.premierleague.com/api/draft/league/{}/transactions"


@st.cache_data(ttl=15)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_active_and_finished_gws():
    """Safely retrieves sets of gameweeks that have started or finished."""
    started_gws = set()
    finished_gws = set()

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if data and isinstance(data, dict):
            matches = data.get("matches", [])
            for m in matches:
                if isinstance(m, dict):
                    gw = m.get("event")
                    if m.get("started"):
                        started_gws.add(gw)
                    if m.get("finished"):
                        finished_gws.add(gw)

    return started_gws, finished_gws


def get_all_teams():
    """Fetch teams from both leagues with guaranteed 16 team fallback."""
    teams = []
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        league_entries = data.get("league_entries", []) if (data and isinstance(data, dict)) else []
        
        for e in league_entries:
            t_name = f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
            e_id = e.get("id")
            teams.append({
                "league_id": l_id,
                "entry_id": e_id,
                "name": t_name,
                "is_placeholder": False
            })
        
        registered_count = len(league_entries)
        for p in range(registered_count + 1, 9):
            teams.append({
                "league_id": l_id,
                "entry_id": None,
                "name": f"Placeholder Team {p} (L-{l_id})",
                "is_placeholder": True
            })
            
    # Guarantee at least 16 entries to avoid IndexError
    while len(teams) < 16:
        teams.append({
            "league_id": 0,
            "entry_id": None,
            "name": f"Placeholder Team {len(teams)+1}",
            "is_placeholder": True
        })
        
    return teams[:16]


def get_gw_team_points(teams):
    """Retrieve score matrix for all teams per Gameweek (GW1 to GW38)."""
    scores = {t["name"]: {gw: 0 for gw in range(1, 39)} for t in teams}
    season_pts = {t["name"]: 0 for t in teams}

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if not data or not isinstance(data, dict):
            continue
            
        matches = data.get("matches", [])
        entry_map = {
            e.get("id"): f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})" 
            for e in data.get("league_entries", []) if isinstance(e, dict)
        }
        
        for s in data.get("standings", []):
            t_name = entry_map.get(s.get("league_entry"))
            if t_name in season_pts:
                season_pts[t_name] = s.get("points_for", 0)

        for m in matches:
            if isinstance(m, dict):
                gw = m.get("event")
                if gw and 1 <= gw <= 38:
                    e1 = entry_map.get(m.get("league_entry_1"))
                    e2 = entry_map.get(m.get("league_entry_2"))
                    if e1 in scores:
                        scores[e1][gw] += m.get("league_entry_1_points", 0)
                    if e2 in scores:
                        scores[e2][gw] += m.get("league_entry_2_points", 0)

    return scores, season_pts


def generate_round_robin_fixtures(team_names):
    """Generates 15 matchdays (GW4 to GW18) using circle method algorithm."""
    n = len(team_names)
    teams = list(team_names)
    fixtures = []

    for md in range(1, n):
        gw = md + 3  # GW4 to GW18
        for i in range(n // 2):
            t1 = teams[i]
            t2 = teams[n - 1 - i]
            
            if md % 2 == 0:
                home, away = t1, t2
            else:
                home, away = t2, t1
                
            fixtures.append({
                "Gameweek": gw,
                "Matchday": md,
                "Home Team": home,
                "Away Team": away
            })
            
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
        
    return fixtures


# --- Load Base Data ---
started_gws, finished_gws = get_active_and_finished_gws()
teams = get_all_teams()
team_names = [t["name"] for t in teams]
scores, season_pts = get_gw_team_points(teams)
group_fixtures = generate_round_robin_fixtures(team_names)

# --- App Render ---
st.title("Craft & Draft Champions League Group Phase")

# 1. PROCESS GROUP FIXTURES & RESULTS TABLE
results_data = []
group_stats = {t: {"Played": 0, "Wins": 0, "Draws": 0, "Losses": 0, "Points For": 0, "Points": 0} for t in team_names}

for f in group_fixtures:
    gw = f["Gameweek"]
    md = f["Matchday"]
    home = f["Home Team"]
    away = f["Away Team"]
    
    h_pts = scores.get(home, {}).get(gw, 0)
    a_pts = scores.get(away, {}).get(gw, 0)
    
    is_active = gw in started_gws or gw in finished_gws

    if is_active:
        group_stats[home]["Points For"] += h_pts
        group_stats[away]["Points For"] += a_pts
        group_stats[home]["Played"] += 1
        group_stats[away]["Played"] += 1

        if h_pts > a_pts:
            score_str = "1 - 0"
            group_stats[home]["Wins"] += 1
            group_stats[home]["Points"] += 3
            group_stats[away]["Losses"] += 1
        elif a_pts > h_pts:
            score_str = "0 - 1"
            group_stats[away]["Wins"] += 1
            group_stats[away]["Points"] += 3
            group_stats[home]["Losses"] += 1
        else:
            score_str = "0 - 0 (Draw)"
            group_stats[home]["Draws"] += 1
            group_stats[home]["Points"] += 1
            group_stats[away]["Draws"] += 1
            group_stats[away]["Points"] += 1
        
        status_str = "Finished" if gw in finished_gws else "Live"
    else:
        score_str = "v"
        status_str = "Scheduled"

    results_data.append({
        "Gameweek": gw,
        "Matchday": md,
        "Home Team": home,
        "Total Points (H)": h_pts if is_active else "-",
        "Away Team": away,
        "Total Points (A)": a_pts if is_active else "-",
        "Score": score_str,
        "Status": status_str
    })

df_results = pd.DataFrame(results_data)

# 2. SORT GROUP STANDINGS TIEBREAKERS
def standings_sort_key(t_name):
    s = group_stats[t_name]
    return (s["Points"], s["Points For"], season_pts.get(t_name, 0), t_name)

sorted_teams = sorted(team_names, key=standings_sort_key, reverse=True)

standings_rows = []
for idx, name in enumerate(sorted_teams, 1):
    st_data = group_stats[name]
    status = "🟢 Qualifies" if idx <= 8 else "🔴 Risk of Elimination"
    standings_rows.append({
        "Rank": idx,
        "Status": status,
        "Team Name": name,
        "Number of games played": st_data["Played"],
        "Wins": st_data["Wins"],
        "Draws": st_data["Draws"],
        "Losses": st_data["Losses"],
        "Points For": st_data["Points For"],
        "Points": st_data["Points"]
    })

df_standings = pd.DataFrame(standings_rows)

# Display Standings Table
st.dataframe(df_standings, use_container_width=True, hide_index=True)

st.divider()

# Display Results Table
st.subheader("C&D CL Group Phase Fixtures and Results")
st.dataframe(df_results, use_container_width=True, hide_index=True, height=400)

st.divider()

# =========================================================
# 3. KNOCKOUT STAGE COMPONENT
# =========================================================
st.subheader("🏆 Knockout")

# Safe slice guaranteeing 8 items
top_8 = sorted_teams[:8] if len(sorted_teams) >= 8 else sorted_teams + [f"Seed {i+1}" for i in range(len(sorted_teams), 8)]

def run_knockout_series(team_a_name, team_b_name, matchdays, et_gw, is_unlocked):
    score_a, score_b = 0, 0
    records = []
    played_games = 0

    for gw in matchdays:
        is_active = (gw in started_gws or gw in finished_gws) and is_unlocked
        pa = scores.get(team_a_name, {}).get(gw, 0) if is_active else 0
        pb = scores.get(team_b_name, {}).get(gw, 0) if is_active else 0
        
        if is_active:
            played_games += 1
            if pa > pb:
                ga, gb = 1, 0
                score_a += 1
            elif pb > pa:
                ga, gb = 0, 1
                score_b += 1
            else:
                ga, gb = 0, 0
        else:
            ga, gb = "-", "-"

        records.append({
            "GW": f"GW {gw}",
            "Team A Name": team_a_name,
            "Team A Pts": pa if is_active else "-",
            "Team A Score": ga,
            "Team B Score": gb,
            "Team B Pts": pb if is_active else "-",
            "Team B Name": team_b_name
        })

    is_tied_after_series = (played_games == len(matchdays)) and (score_a == score_b)
    
    if is_tied_after_series:
        is_et_active = (et_gw in started_gws or et_gw in finished_gws) and is_unlocked
        pa_et = scores.get(team_a_name, {}).get(et_gw, 0) if is_et_active else 0
        pb_et = scores.get(team_b_name, {}).get(et_gw, 0) if is_et_active else 0
        
        if is_et_active:
            if pa_et >= pb_et:
                score_a += 1
                ga_et, gb_et = 1, 0
            else:
                score_b += 1
                ga_et, gb_et = 0, 1
        else:
            ga_et, gb_et = "-", "-"

        records.append({
            "GW": f"GW {et_gw} (ET)",
            "Team A Name": team_a_name,
            "Team A Pts": pa_et if is_et_active else "-",
            "Team A Score": ga_et,
            "Team B Score": gb_et,
            "Team B Pts": pb_et if is_et_active else "-",
            "Team B Name": team_b_name
        })

    winner = team_a_name if score_a >= score_b else team_b_name
    return winner, pd.DataFrame(records)


# --- CHECK ROUND UNLOCK STATUS ---
qf_unlocked = 18 in finished_gws
sf_unlocked = 23 in finished_gws
final_unlocked = 30 in finished_gws

# --- QUARTER-FINALS (GW22 & GW23, ET GW24) ---
qf_pairs = [
    (top_8[7] if qf_unlocked else "8th Place", top_8[0] if qf_unlocked else "1st Place", "A"),
    (top_8[4] if qf_unlocked else "5th Place", top_8[3] if qf_unlocked else "4th Place", "B"),
    (top_8[5] if qf_unlocked else "6th Place", top_8[2] if qf_unlocked else "3rd Place", "C"),
    (top_8[6] if qf_unlocked else "7th Place", top_8[1] if qf_unlocked else "2nd Place", "D")
]

winners_qf = {}
qf_dfs = {}
for t_a, t_b, code in qf_pairs:
    winner, df_series = run_knockout_series(t_a, t_b, [22, 23], 24, qf_unlocked)
    winners_qf[code] = winner if qf_unlocked else f"Winner of Tie {code}"
    qf_dfs[code] = (t_a, t_b, df_series)

# --- SEMI-FINALS (GW27 to GW30, ET GW31) ---
sf_pairs = [
    (winners_qf["A"], winners_qf["C"], "X"),
    (winners_qf["B"], winners_qf["D"], "Y")
]

winners_sf = {}
sf_dfs = {}
for t_a, t_b, code in sf_pairs:
    winner, df_series = run_knockout_series(t_a, t_b, [27, 28, 29, 30], 31, sf_unlocked)
    winners_sf[code] = winner if sf_unlocked else f"Winner of Semi-Final {code}"
    sf_dfs[code] = (t_a, t_b, df_series)

# --- FINAL (GW34 to GW37, ET GW38) ---
final_winner, df_final = run_knockout_series(winners_sf["X"], winners_sf["Y"], [34, 35, 36, 37], 38, final_unlocked)

# --- DISPLAY FIXTURES ---
st.markdown("### Quarter-Finals (Round 2)")
for code in ["A", "B", "C", "D"]:
    t_a, t_b, df_series = qf_dfs[code]
    st.markdown(f"**Tie {code}: {t_a} vs {t_b}**")
    st.dataframe(df_series, use_container_width=True, hide_index=True)

st.divider()

st.markdown("### Semi-Finals (Round 3)")
for code in ["X", "Y"]:
    t_a, t_b, df_series = sf_dfs[code]
    st.markdown(f"**Semi-Final {code}: {t_a} vs {t_b}**")
    st.dataframe(df_series, use_container_width=True, hide_index=True)

st.divider()

st.markdown("### 🏆 Champions League Final")
st.markdown(f"**Final: {winners_sf['X']} vs {winners_sf['Y']}**")
st.dataframe(df_final, use_container_width=True, hide_index=True)

st.divider()

# --- STAND-ALONE WINNER BANNER ---
is_final_complete = final_unlocked and (37 in finished_gws or 38 in finished_gws)
display_winner = final_winner if is_final_complete else "????"

st.success(f"🥇 **Craft and Draft Champions League Winner: {display_winner}**")
