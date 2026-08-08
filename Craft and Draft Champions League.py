import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Streamlit Page Config ---
st.set_page_config(page_title="Craft & Draft Champions League", layout="wide")
st_autorefresh(interval=10000, key="cd_cl_refresh")

LEAGUE_1_ID = 858
LEAGUE_2_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0"}

BOOTSTRAP_URL = "https://draft.premierleague.com/api/bootstrap-static"
LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"
TX_URL_FMT = "https://draft.premierleague.com/api/draft/league/{}/transactions"


@st.cache_data(ttl=5)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_all_teams():
    """Fetch teams from both leagues (8 each) with placeholders if < 8 registered."""
    teams = []
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        league_entries = data.get("league_entries", []) if data else []
        
        # Pull registered entries
        for e in league_entries:
            t_name = f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
            e_id = e["id"]
            teams.append({
                "league_id": l_id,
                "entry_id": e_id,
                "name": t_name,
                "is_placeholder": False
            })
        
        # Fill missing up to 8 with placeholders
        registered_count = len(league_entries)
        for p in range(registered_count + 1, 9):
            teams.append({
                "league_id": l_id,
                "entry_id": None,
                "name": f"Placeholder Team {p} (L-{l_id})",
                "is_placeholder": True
            })
            
    return teams[:16]


def get_gw_team_points(teams):
    """Retrieve score matrix for all teams per Gameweek (GW1 to GW38)."""
    scores = {t["name"]: {gw: 0 for gw in range(1, 39)} for t in teams}
    season_pts = {t["name"]: 0 for t in teams}

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if not data:
            continue
            
        matches = data.get("matches", [])
        entry_map = {e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})" 
                     for e in data.get("league_entries", [])}
        
        # Standings for overall total season points tiebreaker
        for s in data.get("standings", []):
            t_name = entry_map.get(s.get("league_entry"))
            if t_name in season_pts:
                season_pts[t_name] = s.get("points_for", 0)

        for m in matches:
            gw = m.get("event")
            if gw and 1 <= gw <= 38:
                e1 = entry_map.get(m.get("league_entry_1"))
                e2 = entry_map.get(m.get("league_entry_2"))
                if e1 in scores:
                    scores[e1][gw] += m.get("league_entry_1_points", 0)
                if e2 in scores:
                    scores[e2][gw] += m.get("league_entry_2_points", 0)

    return scores, season_pts


def get_transaction_counts(teams):
    """Fetch transactions per manager for tiebreakers."""
    tx_counts = {t["name"]: 0 for t in teams}
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        tx_data = fetch_json(TX_URL_FMT.format(l_id))
        if not data or not tx_data:
            continue
            
        entry_map = {e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})" 
                     for e in data.get("league_entries", [])}
        
        for tx in tx_data.get("transactions", []):
            e_id = tx.get("entry")
            t_name = entry_map.get(e_id)
            if t_name in tx_counts:
                tx_counts[t_name] += 1
                
    return tx_counts


def generate_round_robin_fixtures(team_names):
    """Generates 15 matchdays (GW4 to GW18) using circle method algorithm."""
    n = len(team_names)
    teams = list(team_names)
    fixtures = []

    for md in range(1, n):
        gw = md + 3  # Starts at GW4 (MD1) -> GW18 (MD15)
        for i in range(n // 2):
            t1 = teams[i]
            t2 = teams[n - 1 - i]
            
            # Alternate home/away each matchday
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
            
        # Rotate teams for round-robin
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
        
    return fixtures


# --- Load Base Data ---
teams = get_all_teams()
team_names = [t["name"] for t in teams]
scores, season_pts = get_gw_team_points(teams)
tx_counts = get_transaction_counts(teams)
group_fixtures = generate_round_robin_fixtures(team_names)

# --- App Render ---
st.title("Craft & Draft Champions League Group Phase")

# 1. PROCESS GROUP FIXTURES & RESULTS TABLE
results_data = []
h2h_matrix = {t: {opp: 0 for opp in team_names} for t in team_names}
group_stats = {t: {"Played": 0, "Wins": 0, "Draws": 0, "Losses": 0, "Points For": 0, "Points": 0} for t in team_names}

for f in group_fixtures:
    gw = f["Gameweek"]
    md = f["Matchday"]
    home = f["Home Team"]
    away = f["Away Team"]
    
    h_pts = scores[home][gw]
    a_pts = scores[away][gw]
    
    # Track points for group stage (GW4 to GW18 inclusive)
    group_stats[home]["Points For"] += h_pts
    group_stats[away]["Points For"] += a_pts
    group_stats[home]["Played"] += 1
    group_stats[away]["Played"] += 1

    if h_pts > a_pts:
        score_str = f"1 - 0"
        group_stats[home]["Wins"] += 1
        group_stats[home]["Points"] += 3
        group_stats[away]["Losses"] += 1
        h2h_matrix[home][away] += 3
    elif a_pts > h_pts:
        score_str = f"0 - 1"
        group_stats[away]["Wins"] += 1
        group_stats[away]["Points"] += 3
        group_stats[home]["Losses"] += 1
        h2h_matrix[away][home] += 3
    else:
        score_str = f"0 - 0 (Draw)"
        group_stats[home]["Draws"] += 1
        group_stats[home]["Points"] += 1
        group_stats[away]["Draws"] += 1
        group_stats[away]["Points"] += 1
        h2h_matrix[home][away] += 1
        h2h_matrix[away][home] += 1

    results_data.append({
        "Gameweek": gw,
        "Matchday": md,
        "Home Team": home,
        "Total Points (H)": h_pts,
        "Away Team": away,
        "Total Points (A)": a_pts,
        "Score": score_str
    })

df_results = pd.DataFrame(results_data)

# 2. SORT GROUP STANDINGS TIEBREAKERS
def standings_sort_key(t_name):
    s = group_stats[t_name]
    pts = s["Points"]
    pf = s["Points For"]
    overall_pf = season_pts.get(t_name, 0)
    return (pts, pf, overall_pf)

sorted_teams = sorted(team_names, key=standings_sort_key, reverse=True)

# Format Standings Dataframe
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
# 3. KNOCKOUT STAGE COMPONENT (TOP 8 TEAMS)
# =========================================================
st.subheader("🏆 Knockout Stage (World Cup Style)")

top_8 = sorted_teams[:8]  # Ranks 1 to 8

def run_knockout_series(team_a, team_b, matchdays, et_gw):
    """Executes multi-week knockout tie logic with goals & extra time."""
    score_a, score_b = 0, 0
    total_pts_a, total_pts_b = 0, 0
    records = []

    for round_num, gw in enumerate(matchdays, 1):
        pa = scores[team_a][gw]
        pb = scores[team_b][gw]
        total_pts_a += pa
        total_pts_b += pb
        
        if pa > pb:
            ga, gb = 1, 0
            score_a += 1
        elif pb > pa:
            ga, gb = 0, 1
            score_b += 1
        else:
            ga, gb = 0, 0

        records.append({
            "GW": gw,
            "Team A Name": team_a,
            "Team A Pts": pa,
            "Team A Score": ga,
            "Team B Score": gb,
            "Team B Pts": pb,
            "Team B Name": team_b
        })

    # Extra Time check if tied after main matchdays
    winner = None
    if score_a > score_b:
        winner = team_a
    elif score_b > score_a:
        winner = team_b
    else:
        # Extra Time GW
        pa_et = scores[team_a][et_gw]
        pb_et = scores[team_b][et_gw]
        total_pts_a += pa_et
        total_pts_b += pb_et
        
        if pa_et > pb_et:
            score_a += 1
            winner = team_a
        elif pb_et > pa_et:
            score_b += 1
            winner = team_b
        else:
            # Total points tiebreaker
            if total_pts_a > total_pts_b:
                winner = team_a
            elif total_pts_b > total_pts_a:
                winner = team_b
            else:
                # Total season points tiebreaker
                winner = team_a if season_pts.get(team_a, 0) >= season_pts.get(team_b, 0) else team_b

        records.append({
            "GW": f"{et_gw} (ET)",
            "Team A Name": team_a,
            "Team A Pts": pa_et,
            "Team A Score": 1 if winner == team_a else 0,
            "Team B Score": 1 if winner == team_b else 0,
            "Team B Pts": pb_et,
            "Team B Name": team_b
        })

    return winner, pd.DataFrame(records)


# --- QUARTER FINALS (GW22 & GW23, ET GW24) ---
st.markdown("### Quarter-Finals (Round 2)")
qf_pairs = [
    (top_8[7], top_8[0], "A"),  # 8th vs 1st
    (top_8[4], top_8[3], "B"),  # 5th vs 4th
    (top_8[5], top_8[2], "C"),  # 6th vs 3rd
    (top_8[6], top_8[1], "D")   # 7th vs 2nd
]

winners_qf = {}
cols = st.columns(2)
for idx, (t_a, t_b, code) in enumerate(qf_pairs):
    winner, df_series = run_knockout_series(t_a, t_b, [22, 23], 24)
    winners_qf[code] = winner
    with cols[idx % 2]:
        st.markdown(f"**Tie {code}: {t_a} vs {t_b}** $\\rightarrow$ **Winner: {winner}**")
        st.dataframe(df_series, use_container_width=True, hide_index=True)


# --- SEMI FINALS (GW27 to GW30, ET GW31) ---
st.markdown("### Semi-Finals (Round 3)")
sf_pairs = [
    (winners_qf["A"], winners_qf["C"], "X"),
    (winners_qf["B"], winners_qf["D"], "Y")
]

winners_sf = {}
cols_sf = st.columns(2)
for idx, (t_a, t_b, code) in enumerate(sf_pairs):
    winner, df_series = run_knockout_series(t_a, t_b, [27, 28, 29, 30], 31)
    winners_sf[code] = winner
    with cols_sf[idx]:
        st.markdown(f"**Semi-Final {code}: {t_a} vs {t_b}** $\\rightarrow$ **Winner: {winner}**")
        st.dataframe(df_series, use_container_width=True, hide_index=True)


# --- FINALS (GW34 to GW37, ET GW38) ---
st.markdown("### 🏆 Champions League Final")
final_winner, df_final = run_knockout_series(winners_sf["X"], winners_sf["Y"], [34, 35, 36, 37], 38)
st.success(f"🎉 **CRAFT & DRAFT CHAMPIONS LEAGUE WINNER: {final_winner}**")
st.dataframe(df_final, use_container_width=True, hide_index=True)
