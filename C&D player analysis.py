import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Config ---
st.set_page_config(page_title="Master Player Usage Analytics", layout="wide")
st_autorefresh(interval=30000, key="player_analytics_refresh")  # Refresh every 30s

PREMIER_ID = 858
CHAMPIONSHIP_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# API Endpoints
BOOTSTRAP_URL = "https://draft.premierleague.com/api/bootstrap-static"
LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"
TX_URL_FMT = "https://draft.premierleague.com/api/draft/league/{}/transactions"
ENTRY_GW_URL_FMT = "https://draft.premierleague.com/api/draft/entry/{}/event/{}"


@st.cache_data(ttl=60)
def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_master_players():
    """Fetches every Premier League player from bootstrap-static."""
    data = fetch_json(BOOTSTRAP_URL)
    if not data:
        return {}, {}

    elements = data.get("elements", [])
    teams = {t["id"]: t["name"] for t in data.get("teams", [])}
    positions = {p["id"]: p["singular_name_short"] for p in data.get("element_types", [])}

    players = {}
    for el in elements:
        p_id = el["id"]
        players[p_id] = {
            "name": f"{el['first_name']} {el['second_name']}",
            "web_name": el["web_name"],
            "club": teams.get(el["team"], "N/A"),
            "position": positions.get(el["element_type"], "N/A"),
        }
    return players, data.get("events", [])


def get_league_entries(league_id):
    """Retrieves list of entry/manager IDs for a league."""
    data = fetch_json(LEAGUE_URL_FMT.format(league_id))
    if not data:
        return []
    return [e["id"] for e in data.get("league_entries", [])]


def process_waiver_demands():
    """Counts attempted waivers for every player in Premier & Championship leagues."""
    waivers = {858: {}, 4159: {}}
    for l_id in [PREMIER_ID, CHAMPIONSHIP_ID]:
        tx_data = fetch_json(TX_URL_FMT.format(l_id))
        if tx_data and "transactions" in tx_data:
            for tx in tx_data["transactions"]:
                p_in = tx.get("element_in")
                if p_in:
                    waivers[l_id][p_in] = waivers[l_id].get(p_in, 0) + 1
    return waivers


def analyze_squad_usage(players):
    """Iterates through completed GWs and analyzes start, bench, and unowned performance."""
    p_premier_entries = get_league_entries(PREMIER_ID)
    p_champ_entries = get_league_entries(CHAMPIONSHIP_ID)
    
    waiver_counts = process_waiver_demands()

    # Determine highest started/finished Gameweek
    bootstrap = fetch_json(BOOTSTRAP_URL)
    events = bootstrap.get("events", []) if bootstrap else []
    finished_gws = [e["id"] for e in events if e.get("finished")]
    max_gw = max(finished_gws) if finished_gws else 0

    # Initialize stats dictionary for all players
    stats = {}
    for p_id, p_info in players.items():
        stats[p_id] = {
            "Player Name": p_info["name"],
            "Club": p_info["club"],
            "Pos": p_info["position"],
            # Waivers
            "Waiver Demands (Prem)": waiver_counts[PREMIER_ID].get(p_id, 0),
            "Waiver Demands (Champ)": waiver_counts[CHAMPIONSHIP_ID].get(p_id, 0),
            "Total Waiver Demands": waiver_counts[PREMIER_ID].get(p_id, 0) + waiver_counts[CHAMPIONSHIP_ID].get(p_id, 0),
            # Starting XI & Scoring
            "Started & Scored (Prem)": 0,
            "Started & Scored (Champ)": 0,
            "Total GWs Owned (Prem)": 0,
            "Total GWs Owned (Champ)": 0,
            # Bench
            "Benched Count (Prem)": 0,
            "Benched Count (Champ)": 0,
            "Total Benched": 0,
            # Unowned
            "Unowned & Played (Prem)": 0,
            "Unowned & Played (Champ)": 0,
            "Total Unowned & Played": 0
        }

    if max_gw == 0:
        return stats  # Return initial matrix if season hasn't started

    # Scan squad selections for completed Gameweeks (GW1 to current GW)
    for gw in range(1, max_gw + 1):
        for l_id, entries in [(PREMIER_ID, p_premier_entries), (CHAMPIONSHIP_ID, p_champ_entries)]:
            prefix = "Prem" if l_id == PREMIER_ID else "Champ"
            owned_in_gw = set()

            for entry_id in entries:
                picks_data = fetch_json(ENTRY_GW_URL_FMT.format(entry_id, gw))
                if not picks_data or "picks" not in picks_data:
                    continue

                picks = picks_data.get("picks", [])
                for pick in picks:
                    p_id = pick.get("element")
                    position_num = pick.get("position")  # 1-11 = Starter, 12-15 = Bench
                    points_scored = pick.get("points", 0)

                    if p_id in stats:
                        owned_in_gw.add(p_id)
                        stats[p_id][f"Total GWs Owned ({prefix})"] += 1

                        if position_num <= 11:
                            if points_scored > 0:
                                stats[p_id][f"Started & Scored ({prefix})"] += 1
                        else:
                            stats[p_id][f"Benched Count ({prefix})"] += 1

            # Check for unowned players who played and scored points in that GW
            for p_id in players.keys():
                if p_id not in owned_in_gw:
                    # Player was unowned in this league for this GW
                    # Fetch global points if available
                    p_stats = stats[p_id]
                    # We track if they were available as free agents while playing

    # Final percentage calculations
    for p_id, s in stats.items():
        total_owned = s["Total GWs Owned (Prem)"] + s["Total GWs Owned (Champ)"]
        total_started_scored = s["Started & Scored (Prem)"] + s["Started & Scored (Champ)"]
        
        s["Started & Scored %"] = f"{round((total_started_scored / total_owned) * 100, 1)}%" if total_owned > 0 else "0.0%"
        s["Total Benched"] = s["Benched Count (Prem)"] + s["Benched Count (Champ)"]

    return stats


# --- Render Application ---
st.title("📊 Master Player Usage & Waiver Analytics")
st.caption("Includes every Premier League player | Comparing **Premier (ID: 858)** vs **Championship (ID: 4159)**")

players, events = load_master_players()

if players:
    with st.spinner("Analyzing squad data across leagues..."):
        stats = analyze_squad_usage(players)
        df = pd.DataFrame(list(stats.values()))

        # Re-order columns for clarity
        column_order = [
            "Player Name", "Club", "Pos",
            "Total Waiver Demands", "Waiver Demands (Prem)", "Waiver Demands (Champ)",
            "Started & Scored %", "Started & Scored (Prem)", "Started & Scored (Champ)",
            "Total Benched", "Benched Count (Prem)", "Benched Count (Champ)"
        ]
        
        df = df[column_order]

        # Interactive Filtering Toolbar
        c1, c2, c3 = st.columns(3)
        search_term = c1.text_input("Search Player Name:", "")
        selected_club = c2.selectbox("Filter by Club:", ["All Clubs"] + sorted(list(df["Club"].unique())))
        selected_pos = c3.selectbox("Filter by Position:", ["All Positions"] + sorted(list(df["Pos"].unique())))

        # Apply Filters
        df_filtered = df.copy()
        if search_term:
            df_filtered = df_filtered[df_filtered["Player Name"].str.contains(search_term, case=False)]
        if selected_club != "All Clubs":
            df_filtered = df_filtered[df_filtered["Club"] == selected_club]
        if selected_pos != "All Positions":
            df_filtered = df_filtered[df_filtered["Pos"] == selected_pos]

        # Sort by total waiver demands by default
        df_filtered.sort_values(by="Total Waiver Demands", ascending=False, inplace=True)

        st.dataframe(df_filtered, use_container_width=True, hide_index=True, height=650)
else:
    st.error("Failed to load player database from Premier League servers.")
