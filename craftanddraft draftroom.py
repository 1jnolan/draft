import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- Page Setup ---
st.set_page_config(page_title="Drafted Players Tracker", layout="wide")

# Auto-refresh every 15 seconds
st_autorefresh(interval=15000, key="fpl_refresh_draft_choices")

LEAGUE_ID = 82158
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LEAGUE_URL = f"https://draft.premierleague.com/api/league/{LEAGUE_ID}/details"
DRAFT_CHOICES_URL = f"https://draft.premierleague.com/api/draft/league/{LEAGUE_ID}/choices"
BOOTSTRAP_URL = "https://draft.premierleague.com/api/bootstrap-static"


@st.cache_data(ttl=300)
def fetch_bootstrap_data():
    """Fetch global player, team, and position data from FPL Draft API."""
    try:
        res = requests.get(BOOTSTRAP_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            elements = data.get("elements", [])
            teams = {t["id"]: t["name"] for t in data.get("teams", [])}
            positions = {p["id"]: p["singular_name_short"] for p in data.get("element_types", [])}
            
            player_map = {}
            for el in elements:
                player_map[el["id"]] = {
                    "Player Name": f"{el['first_name']} {el['second_name']}",
                    "Position": positions.get(el["element_type"], "N/A"),
                    "Club": teams.get(el["team"], "N/A")
                }
            return player_map
    except Exception:
        pass
    return {}


@st.cache_data(ttl=10)
def fetch_json(url):
    """Utility function to safely fetch JSON from FPL API."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


# --- Main App Execution ---
st.title("📋 Drafted Players & Squad Roster")
st.caption(f"League ID: **{LEAGUE_ID}**")

player_map = fetch_bootstrap_data()
league_data = fetch_json(LEAGUE_URL)
draft_data = fetch_json(DRAFT_CHOICES_URL)

if league_data and draft_data and player_map:
    entries = league_data.get("league_entries", [])
    entry_map = {
        e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
        for e in entries
    }

    choices = draft_data.get("choices", [])

    # Check if draft choices exist (Post-Draft vs Pre-Draft)
    if choices:
        drafted_list = []
        for choice in choices:
            element_id = choice.get("element")
            entry_id = choice.get("entry")
            
            player_info = player_map.get(element_id, {
                "Player Name": f"Player {element_id}",
                "Position": "N/A",
                "Club": "N/A"
            })

            drafted_list.append({
                "Pick #": choice.get("index"),
                "Round": choice.get("round"),
                "Player Name": player_info["Player Name"],
                "Position": player_info["Position"],
                "Club": player_info["Club"],
                "Drafted By": entry_map.get(entry_id, f"Entry {entry_id}")
            })

        df_draft = pd.DataFrame(drafted_list)

        # Metrics Top Bar
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Drafted Players", len(df_draft))
        m2.metric("Total Managers", df_draft["Drafted By"].nunique())
        m3.metric("Draft Rounds", df_draft["Round"].max())

        st.divider()

        # Filters
        c1, c2, c3 = st.columns(3)
        selected_manager = c1.selectbox("Filter by Manager:", ["All Managers"] + sorted(list(df_draft["Drafted By"].unique())))
        selected_position = c2.selectbox("Filter by Position:", ["All Positions"] + sorted(list(df_draft["Position"].unique())))
        selected_club = c3.selectbox("Filter by Club:", ["All Clubs"] + sorted(list(df_draft["Club"].unique())))

        # Apply Filters
        df_filtered = df_draft.copy()
        if selected_manager != "All Managers":
            df_filtered = df_filtered[df_filtered["Drafted By"] == selected_manager]
        if selected_position != "All Positions":
            df_filtered = df_filtered[df_filtered["Position"] == selected_position]
        if selected_club != "All Clubs":
            df_filtered = df_filtered[df_filtered["Club"] == selected_club]

        st.dataframe(df_filtered, use_container_width=True, hide_index=True, height=600)

    else:
        # Pre-draft informative state
        st.info("⌛ **Draft Pending:** The draft for League 858 has not taken place yet. Once your live draft finishes, the player rosters and picks will automatically appear here.")

else:
    st.error("Connecting to Premier League servers... Please refresh if data does not load.")
