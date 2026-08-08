import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(
    page_title="FPL Draft Live Dashboard",
    page_icon="⚽",
    layout="wide"
)

LEAGUE_ID = 858
REFRESH_INTERVAL_MS = 5000  # 5 seconds in milliseconds

# --- Frontend Auto-Refresh Trigger ---
count = st_autorefresh(interval=REFRESH_INTERVAL_MS, limit=None, key="fpl_refresh_counter")

# --- Header Section ---
st.title("🏆 FPL Draft Live Dashboard")
st.caption(f"League ID: **{LEAGUE_ID}** | Auto-refreshing every 5 seconds (Refresh Count: {count})")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# API Endpoints
LEAGUE_URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
TRANSACTIONS_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/transactions"
TRADES_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/trades"


@st.cache_data(ttl=3)
def fetch_json(url):
    """Utility function to safely fetch JSON from FPL API with brief TTL cache."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_league_and_fixtures():
    """Extract entry maps, standings, and fixture scores."""
    data = fetch_json(LEAGUE_URL)
    if not data:
        return None, pd.DataFrame(), pd.DataFrame()

    # Entry Mapping
    entries = data.get("league_entries", [])
    entry_map = {
        e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
        for e in entries
    }

    # 1. Standings Data
    standings_raw = data.get("standings", [])
    standings_list = []
    for s in standings_raw:
        e_id = s.get("league_entry")
        standings_list.append({
            "Rank": s.get("rank"),
            "Manager / Team Name": entry_map.get(e_id, f"Entry {e_id}"),
            "Played": s.get("matches_played", 0),
            "Won": s.get("matches_won", 0),
            "Drawn": s.get("matches_drawn", 0),
            "Lost": s.get("matches_lost", 0),
            "Points For": s.get("points_for", 0),
            "Total Points": s.get("total", 0),
        })
    df_standings = pd.DataFrame(standings_list)
    if not df_standings.empty:
        df_standings.sort_values(by="Rank", inplace=True)

    # 2. Fixtures & Live Scores
    matches_raw = data.get("matches", [])
    fixtures_list = []
    for m in matches_raw:
        fixtures_list.append({
            "GW": m.get("event"),
            "Home Team": entry_map.get(m.get("league_entry_1")),
            "Home Score": m.get("league_entry_1_points", 0),
            "Away Score": m.get("league_entry_2_points", 0),
            "Away Team": entry_map.get(m.get("league_entry_2")),
            "Status": "Finished" if m.get("finished") else ("Live" if m.get("started") else "Scheduled")
        })
    df_fixtures = pd.DataFrame(fixtures_list)
    if not df_fixtures.empty:
        df_fixtures.sort_values(by=["GW", "Home Team"], inplace=True)

    return entry_map, df_standings, df_fixtures


def get_transaction_stats(entry_map):
    """Processes free agency and waiver transactions per manager."""
    data = fetch_json(TRANSACTIONS_URL)
    if not data or not entry_map:
        return pd.DataFrame()

    transactions = data.get("transactions", [])
    manager_stats = {e_id: {"attempted": 0, "successful": 0, "gws": set()} for e_id in entry_map.keys()}

    for tx in transactions:
        e_id = tx.get("entry")
        if e_id in manager_stats:
            manager_stats[e_id]["attempted"] += 1
            if tx.get("result") == "a":  # Accepted/successful transaction
                manager_stats[e_id]["successful"] += 1
            if tx.get("event"):
                manager_stats[e_id]["gws"].add(tx.get("event"))

    tx_list = []
    for e_id, stats in manager_stats.items():
        att = stats["attempted"]
        succ = stats["successful"]
        rate = round((succ / att) * 100, 1) if att > 0 else 0.0

        tx_list.append({
            "Manager": entry_map.get(e_id),
            "Attempted Transactions": att,
            "Successful Transactions": succ,
            "Success Rate (%)": f"{rate}%",
            "GWs Active in Market": len(stats["gws"]),
        })

    df_tx = pd.DataFrame(tx_list)
    if not df_tx.empty:
        df_tx.sort_values(by="Attempted Transactions", ascending=False, inplace=True)
    return df_tx


def get_trade_stats(entry_map):
    """Processes successful player trades per manager."""
    data = fetch_json(TRADES_URL)
    if not entry_map:
        return pd.DataFrame()

    trade_counts = {e_id: 0 for e_id in entry_map.keys()}

    if data:
        trades = data.get("trades", [])
        for t in trades:
            if t.get("state") == "p":  # Processed/successful trade
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                if e1 in trade_counts: trade_counts[e1] += 1
                if e2 in trade_counts: trade_counts[e2] += 1

    trades_list = [{
        "Manager": entry_map.get(e_id),
        "Successful Trades Involved": count
    } for e_id, count in trade_counts.items()]

    df_trades = pd.DataFrame(trades_list)
    if not df_trades.empty:
        df_trades.sort_values(by="Successful Trades Involved", ascending=False, inplace=True)
    return df_trades


# --- App Logic & Rendering ---
entry_map, df_standings, df_fixtures = get_league_and_fixtures()

if entry_map:
    df_transactions = get_transaction_stats(entry_map)
    df_trades = get_trade_stats(entry_map)

    # Top Row: Standings and Live Fixtures
    col1, col2 = st.columns([1, 1], gap="medium")

    with col1:
        st.subheader("📊 1. Current League Standings")
        if not df_standings.empty:
            st.dataframe(df_standings, use_container_width=True, hide_index=True)
        else:
            st.info("No standings data available yet.")

    with col2:
        st.subheader("⚡ 2. Gameweek Fixtures & Live Scores")
        if not df_fixtures.empty:
            # Dropdown filter for Gameweeks
            all_gws = sorted(df_fixtures["GW"].unique())
            selected_gw = st.selectbox("Select Gameweek:", all_gws, index=len(all_gws) - 1 if all_gws else 0)
            filtered_fixtures = df_fixtures[df_fixtures["GW"] == selected_gw]
            st.dataframe(filtered_fixtures, use_container_width=True, hide_index=True)
        else:
            st.info("No fixtures data available.")

    st.divider()

    # Bottom Row: Transactions and Trades
    col3, col4 = st.columns([1, 1], gap="medium")

    with col3:
        st.subheader("🔄 3. Transaction Tracker (Waivers & Free Agency)")
        if not df_transactions.empty:
            st.dataframe(df_transactions, use_container_width=True, hide_index=True)
        else:
            st.info("No transaction stats recorded.")

    with col4:
        st.subheader("🤝 4. Player Trade Tracker")
        if not df_trades.empty:
            st.dataframe(df_trades, use_container_width=True, hide_index=True)
        else:
            st.info("No trade data available.")

else:
    st.error("Failed to load data from the FPL Draft API. Retrying automatically...")
