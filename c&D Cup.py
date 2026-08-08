import streamlit as st
import requests
import random
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Streamlit Page Setup ---
st.set_page_config(page_title="Craft & Draft League Cup", layout="wide")
st_autorefresh(interval=10000, key="cd_cup_refresh")

LEAGUE_1_ID = 858
LEAGUE_2_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"


@st.cache_data(ttl=5)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_active_and_finished_gws():
    """Retrieves gameweeks that have officially started or finished."""
    started_gws = set()
    finished_gws = set()

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if data and isinstance(data, dict):
            for m in data.get("matches", []):
                gw = m.get("event")
                if m.get("started"):
                    started_gws.add(gw)
                if m.get("finished"):
                    finished_gws.add(gw)

    return started_gws, finished_gws


def get_all_teams():
    """Fetch 16 teams across both leagues with placeholders if needed."""
    teams = []
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        league_entries = data.get("league_entries", []) if data else []
        
        for e in league_entries:
            t_name = f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
            teams.append(t_name)
        
        registered_count = len(league_entries)
        for p in range(registered_count + 1, 9):
            teams.append(f"Placeholder Team {p} (L-{l_id})")
            
    return sorted(teams[:16])


def get_gw_scores(teams):
    """Retrieve score matrix for all teams across all gameweeks."""
    scores = {t: {gw: 0 for gw in range(1, 39)} for t in teams}

    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if not data:
            continue
            
        entry_map = {e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})" 
                     for e in data.get("league_entries", [])}
        
        for m in data.get("matches", []):
            gw = m.get("event")
            if gw and 1 <= gw <= 38:
                e1 = entry_map.get(m.get("league_entry_1"))
                e2 = entry_map.get(m.get("league_entry_2"))
                if e1 in scores:
                    scores[e1][gw] += m.get("league_entry_1_points", 0)
                if e2 in scores:
                    scores[e2][gw] += m.get("league_entry_2_points", 0)

    return scores


# --- Load Data & Set Fixed Seeded Random Draw ---
started_gws, finished_gws = get_active_and_finished_gws()
all_teams = get_all_teams()
scores = get_gw_scores(all_teams)

# Fixed seed keeps Round 1 draws consistent across app refreshes
random.seed(8584159)
shuffled_teams = all_teams.copy()
random.shuffle(shuffled_teams)

# --- App Render ---
st.title("🏆 Craft & Draft Association Cup")
st.caption("16-Team Knockout Cup Competition | Single Game Weeks with Replays on Draw")


def evaluate_cup_match(team_a, team_b, main_gw, replay_gw, is_unlocked):
    """Evaluates a single-leg cup match with a replay week if tied."""
    is_main_active = (main_gw in started_gws or main_gw in finished_gws) and is_unlocked
    pts_a = scores.get(team_a, {}).get(main_gw, 0) if is_main_active else 0
    pts_b = scores.get(team_b, {}).get(main_gw, 0) if is_main_active else 0

    records = []
    
    # Main Gameweek Match
    if is_main_active:
        res_a = "WIN" if pts_a > pts_b else ("DRAW" if pts_a == pts_b else "LOSS")
        res_b = "WIN" if pts_b > pts_a else ("DRAW" if pts_a == pts_b else "LOSS")
    else:
        res_a, res_b = "-", "-"

    records.append({
        "Stage": f"GW {main_gw}",
        "Home Team": team_a,
        "Home Pts": pts_a if is_main_active else "-",
        "Result": f"{res_a} - {res_b}" if is_main_active else "v",
        "Away Pts": pts_b if is_main_active else "-",
        "Away Team": team_b
    })

    # Replay Check (Triggered only if Main GW ended in a Draw)
    is_replay_needed = is_main_active and (pts_a == pts_b) and (main_gw in finished_gws)
    winner = None

    if is_replay_needed:
        is_replay_active = (replay_gw in started_gws or replay_gw in finished_gws) and is_unlocked
        r_pts_a = scores.get(team_a, {}).get(replay_gw, 0) if is_replay_active else 0
        r_pts_b = scores.get(team_b, {}).get(replay_gw, 0) if is_replay_active else 0
        
        if is_replay_active:
            if r_pts_a > r_pts_b:
                winner = team_a
            elif r_pts_b > r_pts_a:
                winner = team_b
            else:
                winner = team_a if pts_a >= pts_b else team_b

        records.append({
            "Stage": f"GW {replay_gw} (Replay)",
            "Home Team": team_a,
            "Home Pts": r_pts_a if is_replay_active else "-",
            "Result": "REPLAY" if is_replay_active else "v",
            "Away Pts": r_pts_b if is_replay_active else "-",
            "Away Team": team_b
        })
    elif is_main_active and main_gw in finished_gws:
        winner = team_a if pts_a > pts_b else team_b
    else:
        winner = team_a

    return winner, pd.DataFrame(records)


# =========================================================
# ROUND 1: GW 20 (Replay: GW 21)
# =========================================================
st.subheader("🥇 Round 1 (Gameweek 20 | Replay: Gameweek 21)")

r1_unlocked = True
r1_winners = []
r1_cols = st.columns(2)

for i in range(8):
    t_a = shuffled_teams[i * 2]
    t_b = shuffled_teams[i * 2 + 1]
    
    winner, df_match = evaluate_cup_match(t_a, t_b, main_gw=20, replay_gw=21, is_unlocked=r1_unlocked)
    r1_winners.append(winner if 20 in finished_gws else f"Winner Match {i+1}")
    
    with r1_cols[i % 2]:
        st.markdown(f"**Match {i+1}: {t_a} vs {t_b}**")
        st.dataframe(df_match, use_container_width=True, hide_index=True)

st.divider()

# =========================================================
# LAST 8 / QUARTER-FINALS: GW 25 (Replay: GW 26)
# =========================================================
st.subheader("🥈 Quarter-Finals / Last 8 (Gameweek 25 | Replay: Gameweek 26)")

qf_unlocked = 20 in finished_gws or 21 in finished_gws
qf_winners = []
qf_cols = st.columns(2)

for i in range(4):
    t_a = r1_winners[i * 2]
    t_b = r1_winners[i * 2 + 1]
    
    winner, df_match = evaluate_cup_match(t_a, t_b, main_gw=25, replay_gw=26, is_unlocked=qf_unlocked)
    qf_winners.append(winner if 25 in finished_gws else f"Winner QF {i+1}")
    
    with qf_cols[i % 2]:
        st.markdown(f"**QF Match {i+1}: {t_a} vs {t_b}**")
        st.dataframe(df_match, use_container_width=True, hide_index=True)

st.divider()

# =========================================================
# SEMI-FINALS: GW 29 (Replay: GW 30)
# =========================================================
st.subheader("🥉 Semi-Finals (Gameweek 29 | Replay: Gameweek 30)")

sf_unlocked = 25 in finished_gws or 26 in finished_gws
sf_winners = []
sf_cols = st.columns(2)

for i in range(2):
    t_a = qf_winners[i * 2]
    t_b = qf_winners[i * 2 + 1]
    
    winner, df_match = evaluate_cup_match(t_a, t_b, main_gw=29, replay_gw=30, is_unlocked=sf_unlocked)
    sf_winners.append(winner if 29 in finished_gws else f"Winner SF {i+1}")
    
    with sf_cols[i]:
        st.markdown(f"**SF Match {i+1}: {t_a} vs {t_b}**")
        st.dataframe(df_match, use_container_width=True, hide_index=True)

st.divider()

# =========================================================
# FINAL: GW 31 (Replay: GW 32)
# =========================================================
st.subheader("🏆 League Cup Final (Gameweek 31 | Replay: Gameweek 32)")

final_unlocked = 29 in finished_gws or 30 in finished_gws
cup_winner, df_final = evaluate_cup_match(sf_winners[0], sf_winners[1], main_gw=31, replay_gw=32, is_unlocked=final_unlocked)

st.markdown(f"**Final: {sf_winners[0]} vs {sf_winners[1]}**")
st.dataframe(df_final, use_container_width=True, hide_index=True)
