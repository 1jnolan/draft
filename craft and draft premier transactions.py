import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(page_title="Waiver & Trade Market Tracker", layout="wide")

# Auto-refresh every 30 seconds
st_autorefresh(interval=30000, key="fpl_refresh_app3_4")

LEAGUE_ID = 858
LEAGUE_URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
TX_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/transactions"
TRADES_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/trades"
BOOTSTRAP_URL = "https://draft.premierleague.com/api/bootstrap-static"
EVENT_LIVE_URL = "https://draft.premierleague.com/api/event/{}/live"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


@st.cache_data(ttl=300)
def fetch_player_metadata():
    """Fetch player names, positions, and teams from bootstrap-static."""
    try:
        res = requests.get(BOOTSTRAP_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            teams = {t["id"]: t["short_name"] for t in data.get("teams", [])}
            positions = {p["id"]: p["singular_name_short"] for p in data.get("element_types", [])}

            player_map = {}
            for el in data.get("elements", []):
                name = el.get("web_name") or f"{el.get('first_name', '')} {el.get('second_name', '')}".strip()
                player_map[el["id"]] = {
                    "name": name,
                    "team": teams.get(el.get("team"), "N/A"),
                    "position": positions.get(el.get("element_type"), "N/A"),
                }
            return player_map
    except Exception:
        pass
    return {}


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


@st.cache_data(ttl=15)
def fetch_json(url):
    """Safely fetch JSON data from the FPL Draft API with short caching."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


# --- Fetch Core Data ---
player_map = fetch_player_metadata()
league_data = fetch_json(LEAGUE_URL)
tx_data = fetch_json(TX_URL)
trades_data = fetch_json(TRADES_URL)

st.title("🔄 Waiver & Transfer ROI Market Tracker")
st.caption(f"League ID: **{LEAGUE_ID}**")

if league_data and isinstance(league_data, dict):
    entries = league_data.get("league_entries", [])

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
    # PROCESS TRANSACTIONS & POINTS IMPACT
    # ==========================================
    player_counts = {}
    transfer_log = []
    gw_scores_cache = {}

    manager_stats = {
        m_name: {
            "waiver_att": 0,
            "waiver_succ": 0,
            "fa_succ": 0,
            "pts_in": 0,
            "pts_out": 0,
            "gws": set(),
        }
        for m_name in manager_names
    }

    # Data structure to track points gained per manager per gameweek
    # {manager_name: {gw_number: points_in}}
    manager_gw_pts_in = {m_name: {} for m_name in manager_names}
    all_active_gws = set()

    if tx_data and isinstance(tx_data, dict):
        transactions = tx_data.get("transactions", [])

        for tx in transactions:
            if not isinstance(tx, dict):
                continue

            raw_id = tx.get("entry") or tx.get("league_entry")
            m_name = id_to_name.get(raw_id)
            kind = tx.get("kind")  # 'w' = waiver, 'f' = free agency
            result = tx.get("result")  # 'a' = accepted
            gw = tx.get("event")
            is_successful = (result == "a") or (kind == "f")

            if m_name and m_name in manager_stats:
                if gw:
                    manager_stats[m_name]["gws"].add(gw)

                if kind == "w":
                    manager_stats[m_name]["waiver_att"] += 1
                    if result == "a":
                        manager_stats[m_name]["waiver_succ"] += 1
                elif kind == "f":
                    manager_stats[m_name]["fa_succ"] += 1

            if is_successful and gw:
                all_active_gws.add(gw)
                el_in = tx.get("element_in")
                el_out = tx.get("element_out")
                move_type = "Waiver" if kind == "w" else "Free Agency"

                # Pull GW live scores for this gameweek
                if gw not in gw_scores_cache:
                    gw_scores_cache[gw] = fetch_gw_live_scores(gw)
                current_gw_scores = gw_scores_cache[gw]

                in_pts = current_gw_scores.get(el_in, 0) if el_in else 0
                out_pts = current_gw_scores.get(el_out, 0) if el_out else 0
                net_pts = in_pts - out_pts

                if m_name and m_name in manager_stats:
                    manager_stats[m_name]["pts_in"] += in_pts
                    manager_stats[m_name]["pts_out"] += out_pts
                    manager_gw_pts_in[m_name][gw] = manager_gw_pts_in[m_name].get(gw, 0) + in_pts

                # Player aggregate tracking
                if el_in:
                    if el_in not in player_counts:
                        player_counts[el_in] = {"in": 0, "out": 0}
                    player_counts[el_in]["in"] += 1

                if el_out:
                    if el_out not in player_counts:
                        player_counts[el_out] = {"in": 0, "out": 0}
                    player_counts[el_out]["out"] += 1

                # Transfer % improvement calculation
                if out_pts > 0:
                    tx_pct = round(((in_pts - out_pts) / out_pts) * 100, 1)
                    tx_pct_str = f"+{tx_pct}%" if tx_pct > 0 else f"{tx_pct}%"
                elif in_pts > 0:
                    tx_pct_str = "+100% (Pure Gain)"
                else:
                    tx_pct_str = "0.0%"

                p_in_info = (player_map or {}).get(el_in, {"name": f"Player {el_in}", "team": "-", "position": "-"})
                p_out_info = (player_map or {}).get(el_out, {"name": f"Player {el_out}", "team": "-", "position": "-"})

                transfer_log.append({
                    "Gameweek": f"GW {gw}",
                    "Manager": m_name or f"Manager ({raw_id})",
                    "Type": move_type,
                    "Player In": f"{p_in_info['name']} ({p_in_info['team']})",
                    "Pts In": in_pts,
                    "Player Out": f"{p_out_info['name']} ({p_out_info['team']})",
                    "Pts Out": out_pts,
                    "Net Pts": f"+{net_pts}" if net_pts > 0 else str(net_pts),
                    "Transfer ROI": tx_pct_str,
                })

    # ==========================================
    # SECTION 1: Manager Waiver Activity & Net Points ROI
    # ==========================================
    st.subheader("📈 Manager Waiver Activity & Net Points Impact")

    tx_list = []
    for m_name, stats in manager_stats.items():
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

    st.divider()

    # ==========================================
    # SECTION 2: Manager-to-Manager Trades
    # ==========================================
    st.subheader("🤝 Manager-to-Manager Trades Tracker")

    trade_counts = {m_name: 0 for m_name in manager_names}
    if trades_data and isinstance(trades_data, dict):
        trades = trades_data.get("trades", [])
        for t in trades:
            if isinstance(t, dict) and t.get("state") == "p":
                e1 = t.get("offered_entry")
                e2 = t.get("received_entry")
                name1 = id_to_name.get(e1)
                name2 = id_to_name.get(e2)
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

    st.divider()

    # ==========================================
    # SECTION 3: Player Movement Aggregates
    # ==========================================
    st.subheader("📊 Most Transferred Players (In & Out)")

    player_summary = []
    for p_id, counts in player_counts.items():
        info = (player_map or {}).get(p_id, {"name": f"Player {p_id}", "team": "-", "position": "-"})
        times_in = counts["in"]
        times_out = counts["out"]
        total_activity = times_in + times_out
        net_movement = times_in - times_out

        player_summary.append({
            "Player": info["name"],
            "Club": info["team"],
            "Pos": info["position"],
            "Times Brought IN": times_in,
            "Times Dropped OUT": times_out,
            "Total Transactions": total_activity,
            "Net Movement (+/-)": f"+{net_movement}" if net_movement > 0 else str(net_movement),
        })

    df_players = pd.DataFrame(player_summary)
    if not df_players.empty:
        df_players.sort_values(by=["Total Transactions", "Times Brought IN"], ascending=[False, False], inplace=True)
        st.dataframe(df_players, use_container_width=True, hide_index=True)
    else:
        st.info("No player transfers recorded yet this season.")

    st.divider()

    # ==========================================
    # SECTION 4: Detailed Transaction & Gameweek ROI Log
    # ==========================================
    st.subheader("📜 Detailed Roster Move & Gameweek Points Impact Log")

    df_log = pd.DataFrame(transfer_log)
    if not df_log.empty:
        all_managers = ["All Managers"] + sorted(list(df_log["Manager"].unique()))
        selected_mgr = st.selectbox("Filter moves by Manager:", all_managers)

        if selected_mgr != "All Managers":
            df_display_log = df_log[df_log["Manager"] == selected_mgr]
        else:
            df_display_log = df_log

        st.dataframe(df_display_log, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("No transaction history available yet.")

    st.divider()

    # ==========================================
    # SECTION 5: Manager Gameweek Transfer Points Leaderboard
    # ==========================================
    st.subheader("🏆 Manager Gameweek Transfer Points Leaderboard")
    st.caption("Ranks managers by the total points generated by incoming players in each Gameweek and across the full season.")

    sorted_gws = sorted(list(all_active_gws))

    gw_leaderboard_rows = []
    for m_name in manager_names:
        row = {"Manager": m_name}
        total_pts_all_gws = 0
        for gw_num in sorted_gws:
            pts = manager_gw_pts_in.get(m_name, {}).get(gw_num, 0)
            row[f"GW {gw_num} Pts In"] = pts
            total_pts_all_gws += pts
        row["Total Transfer Points"] = total_pts_all_gws
        gw_leaderboard_rows.append(row)

    df_gw_leaderboard = pd.DataFrame(gw_leaderboard_rows)

    if not df_gw_leaderboard.empty:
        # Sort managers by highest cumulative transfer points
        df_gw_leaderboard.sort_values(by="Total Transfer Points", ascending=False, inplace=True)
        df_gw_leaderboard.reset_index(drop=True, inplace=True)

        # Assign clean visual rank strings
        df_gw_leaderboard.insert(0, "Rank", range(1, len(df_gw_leaderboard) + 1))
        st.dataframe(df_gw_leaderboard, use_container_width=True, hide_index=True)
    else:
        st.info("Gameweek transfer leaderboard will populate as Gameweeks finish.")

else:
    st.error("Connecting to Premier League servers... Please refresh if data does not load.")
