@st.cache_data(ttl=120)
def fetch_fotmob_predictions_standings():
    """Fetches prediction data or provides league details if rendered client-side."""
    try:
        res = requests.get(FOTMOB_PAGE_URL, headers=HEADERS, timeout=8)
        if res.status_code == 200 and "__NEXT_DATA__" in res.text:
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                page_props = data.get("props", {}).get("pageProps", {})
                leaderboard = page_props.get("leaderboard") or page_props.get("standings") or []
                if leaderboard:
                    rows = []
                    for item in leaderboard:
                        rows.append({
                            "Rank": item.get("rank", "-"),
                            "Participant": item.get("userName") or item.get("name", "Unknown"),
                            "Total Points": item.get("totalPoints", 0),
                            "Exact Scores": item.get("exactScores", "-"),
                            "Correct Outcomes": item.get("correctOutcomes", "-")
                        })
                    return pd.DataFrame(rows)
    except Exception:
        pass
    return pd.DataFrame()
