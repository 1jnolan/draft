import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(page_title="Waiver & Trade Market Tracker", layout="wide")

# Auto-refresh every 30 seconds (prevents memory leaks)
st_autorefresh(interval=30000, key="fpl_refresh_app3_4")

LEAGUE_ID = 858
LEAGUE_URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
TX_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/transactions"
TRADES_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/trades"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


@st.cache_data(ttl=15)
def fetch_json(url):
    """Safely fetch JSON data from the FPL Draft API with short caching."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


# --- Fetch Data ---
league_data = fetch_json(LEAGUE_URL)
tx_data = fetch_json(TX_URL)
trades_data = fetch_json(TRADES_URL)

if league_data and isinstance(league_data, dict):
    entries = league_data.get("league_entries", [])
    
    # 1. Map both 'id' and 'entry_id' to the manager's display name
    id_to_name = {}
    manager_names = []
    
    for e in entries:
        if isinstance(e, dict):
            name = f"{e.get('entry_name', 'Team')} ({e.get('player_first_name', '')} {e.get('player_last_name', '')})"
            manager_names.append(name)
            if "id" in e:
                id_to_name[e["id"]] = name
            if "entry_id" in e:
                id_to_name[e["entry_id"]] = name

    # ==========================================
    # SECTION 1: Waiver & Free Agency Tracker
    # ==========================================
    st.subheader("🔄 Waiver & Free Agency Market Tracker")

    if tx_data and isinstance(tx_data, dict):
        transactions = tx_data.get("transactions", [])
        
        # Initialize stats using manager name as primary key
        manager_stats = {
            m_name: {
                "waiver_att": 0,
                "waiver_succ": 0,
                "fa_succ": 0,
                "total_transfers": 0,
                "gws": set()
            }
            for m_name in manager_names
        }

        for tx in transactions:
            if not isinstance(tx, dict):
                continue
                
            # Handle both 'entry' and 'league_entry'
            raw_id = tx.get("entry") or tx.get("league_entry")
            m_name = id_to_name.get(raw_id)
            
            if m_name and m_name in manager_stats:
                kind = tx.get("kind")  # 'w' = waiver, 'f' = free agent
                result = tx.get("result")  # 'a' = accepted, 'di' = decision ignored, etc.
                gw = tx.get("event")

                if gw:
                    manager_stats[m_name]["gws"].add(gw)

                if kind == "w":
                    manager_stats[m_name]["waiver_att"] += 1
                    if result == "a":
                        manager_stats[m_name]["waiver_succ"] += 1
                        manager_stats[m_name]["total_transfers"] += 1
                elif kind == "f":
                    # Free agent pickups are instant accepted transactions
                    manager_stats[m_name]["fa_succ"] += 1
                    manager_stats[m_name]["total_transfers"] += 1

        tx_list = []
        for m_name, stats in manager_stats.items():
            att = stats["waiver_att"]
            succ = stats["waiver_succ"]
            fa = stats["fa_succ"]
            total = stats["total_transfers"]
            rate = round((succ / att) * 100, 1) if att > 0 else 0.0

            tx_list.append({
                "Manager": m_name,
                "Successful Transfers": total,
                "Waivers Won": succ,
                "Waivers Attempted": att,
                "Waiver Success Rate": f"{rate}%",
                "Free Agent Pickups": fa,
                "Active GWs": len(stats["gws"]),
            })

        df_tx = pd.DataFrame(tx_list)
        if not df_tx.empty:
            df_tx.sort_values(by=["Successful Transfers", "Waivers Attempted"], ascending=[False, False], inplace=True)
            st.dataframe(df_tx, use_container_width=True, hide_index=True)
        else:
            st.info("No transaction stats recorded.")
    else:
        st.info("No waiver or transaction data available yet.")

    st.divider()

    # ==========================================
    # SECTION 2: Manager-to-Manager Trades
    # ==========================================
    st.subheader("🤝 Manager-to-Manager Trades Tracker")

    trade_counts = {m_name: 0 for m_name in manager_names}

    if trades_data and isinstance(trades_data, dict):
        trades = trades_data.get("trades", [])
        for t in trades:
            if isinstance(t, dict) and t.get("state") == "p":  # 'p' = processed
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                
                name1 = id_to_name.get(e1)
                name2 = id_to_name.get(e2)
                
                if name1 in trade_counts:
                    trade_counts[name1] += 1
                if name2 in trade_counts:
                    trade_counts[name2] += 1

    trades_list = [{
        "Manager": m_name,
        "Completed Trades Involved": count
    } for m_name, count in trade_counts.items()]

    df_trades = pd.DataFrame(trades_list)
    if not df_trades.empty:
        df_trades.sort_values(by="Completed Trades Involved", ascending=False, inplace=True)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No completed trade data available.")

else:
    st.error("Connecting to Premier League servers... Please refresh if data does not load.")
