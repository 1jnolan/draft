import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(page_title="Waiver & Trade Market Tracker", layout="wide")

# Auto-refresh every 10 seconds (10000 ms)
st_autorefresh(interval=10000, key="fpl_refresh_app3_4")

LEAGUE_ID = 858
LEAGUE_URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
TX_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/transactions"
TRADES_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/trades"
HEADERS = {"User-Agent": "Mozilla/5.0"}


@st.cache_data(ttl=5)
def fetch_json(url):
    """Safely fetch JSON data from the FPL Draft API with short caching."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


# --- Fetch Data ---
league_data = fetch_json(LEAGUE_URL)
tx_data = fetch_json(TX_URL)
trades_data = fetch_json(TRADES_URL)

if league_data:
    entries = league_data.get("league_entries", [])
    entry_map = {
        e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
        for e in entries
    }

    # ==========================================
    # SECTION 1: Waiver & Free Agency Tracker
    # ==========================================
    st.subheader("🔄 Waiver & Free Agency Market Tracker")

    if tx_data:
        transactions = tx_data.get("transactions", [])
        manager_stats = {
            e_id: {"attempted": 0, "successful": 0, "gws": set()}
            for e_id in entry_map.keys()
        }

        for tx in transactions:
            e_id = tx.get("entry")
            if e_id in manager_stats:
                manager_stats[e_id]["attempted"] += 1
                if tx.get("result") == "a":  # 'a' = accepted/successful
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
                "Attempted Waivers": att,
                "Successful Waivers": succ,
                "Success Rate (%)": f"{rate}%",
                "GWs Active in Market": len(stats["gws"]),
            })

        df_tx = pd.DataFrame(tx_list)
        if not df_tx.empty:
            df_tx.sort_values(by="Attempted Waivers", ascending=False, inplace=True)
            st.dataframe(df_tx, use_container_width=True, hide_index=True)
        else:
            st.info("No transaction stats recorded.")
    else:
        st.warning("Failed to load transaction data.")

    st.divider()

    # ==========================================
    # SECTION 2: Manager-to-Manager Trades
    # ==========================================
    st.subheader("🤝 Manager-to-Manager Trades Tracker")

    trade_counts = {e_id: 0 for e_id in entry_map.keys()}

    if trades_data:
        trades = trades_data.get("trades", [])
        for t in trades:
            if t.get("state") == "p":  # 'p' = processed/successful trade
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                if e1 in trade_counts:
                    trade_counts[e1] += 1
                if e2 in trade_counts:
                    trade_counts[e2] += 1

    trades_list = [{
        "Manager": entry_map.get(e_id),
        "Completed Trades Involved": count
    } for e_id, count in trade_counts.items()]

    df_trades = pd.DataFrame(trades_list)
    if not df_trades.empty:
        df_trades.sort_values(by="Completed Trades Involved", ascending=False, inplace=True)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No trade data available.")

else:
    st.error("Failed to load league details from the FPL Draft API.")
