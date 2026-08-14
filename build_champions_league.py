import os
import requests
import pandas as pd
from datetime import datetime

LEAGUE_1_ID = 858
LEAGUE_2_ID = 4159
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
LEAGUE_URL_FMT = "https://draft.premierleague.com/api/league/{}/details"


def fetch_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


def get_active_and_finished_gws():
    started_gws = set()
    finished_gws = set()
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if data and isinstance(data, dict):
            for m in data.get("matches", []):
                if isinstance(m, dict):
                    gw = m.get("event")
                    if m.get("started"):
                        started_gws.add(gw)
                    if m.get("finished"):
                        finished_gws.add(gw)
    return started_gws, finished_gws


def get_all_teams():
    teams = []
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        league_entries = data.get("league_entries", []) if data else []
        for e in league_entries:
            teams.append({
                "league_id": l_id,
                "name": f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})"
            })
        registered_count = len(league_entries)
        for p in range(registered_count + 1, 9):
            teams.append({
                "league_id": l_id,
                "name": f"Placeholder Team {p} (L-{l_id})"
            })
    return teams[:16]


def get_gw_team_points(teams):
    scores = {t["name"]: {gw: 0 for gw in range(1, 39)} for t in teams}
    season_pts = {t["name"]: 0 for t in teams}
    for l_id in [LEAGUE_1_ID, LEAGUE_2_ID]:
        data = fetch_json(LEAGUE_URL_FMT.format(l_id))
        if not data:
            continue
        entry_map = {
            e["id"]: f"{e['entry_name']} ({e['player_first_name']} {e['player_last_name']})" 
            for e in data.get("league_entries", [])
        }
        for s in data.get("standings", []):
            t_name = entry_map.get(s.get("league_entry"))
            if t_name in season_pts:
                season_pts[t_name] = s.get("points_for", 0)
        for m in data.get("matches", []):
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
    n = len(team_names)
    teams = list(team_names)
    fixtures = []
    for md in range(1, n):
        gw = md + 3  # GW4 (MD1) to GW18 (MD15)
        for i in range(n // 2):
            t1, t2 = teams[i], teams[n - 1 - i]
            home, away = (t1, t2) if md % 2 == 0 else (t2, t1)
            fixtures.append({
                "Gameweek": gw,
                "Matchday": md,
                "Home Team": home,
                "Away Team": away
            })
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return fixtures


def generate_html():
    started_gws, finished_gws = get_active_and_finished_gws()
    teams = get_all_teams()
    team_names = [t["name"] for t in teams]
    scores, season_pts = get_gw_team_points(teams)
    group_fixtures = generate_round_robin_fixtures(team_names)

    # 1. Process Group Results
    results_data = []
    group_stats = {t: {"Played": 0, "Wins": 0, "Draws": 0, "Losses": 0, "Points For": 0, "Points": 0} for t in team_names}

    for f in group_fixtures:
        gw, md, home, away = f["Gameweek"], f["Matchday"], f["Home Team"], f["Away Team"]
        h_pts, a_pts = scores[home][gw], scores[away][gw]
        is_active = gw in started_gws or gw in finished_gws

        if is_active:
            group_stats[home]["Points For"] += h_pts
            group_stats[away]["Points For"] += a_pts
            group_stats[home]["Played"] += 1
            group_stats[away]["Played"] += 1

            if h_pts > a_pts:
                score_str = "1 - 0"
                group_stats[home]["Wins"] += 1; group_stats[home]["Points"] += 3; group_stats[away]["Losses"] += 1
            elif a_pts > h_pts:
                score_str = "0 - 1"
                group_stats[away]["Wins"] += 1; group_stats[away]["Points"] += 3; group_stats[home]["Losses"] += 1
            else:
                score_str = "0 - 0 (Draw)"
                group_stats[home]["Draws"] += 1; group_stats[home]["Points"] += 1
                group_stats[away]["Draws"] += 1; group_stats[away]["Points"] += 1
            status_str = "Finished" if gw in finished_gws else "Live"
        else:
            score_str, status_str = "v", "Scheduled"

        results_data.append({
            "Gameweek": gw, "Matchday": md, "Home Team": home,
            "Total Points (H)": h_pts if is_active else "-",
            "Away Team": away,
            "Total Points (A)": a_pts if is_active else "-",
            "Score": score_str, "Status": status_str
        })

    sorted_teams = sorted(
        team_names,
        key=lambda t: (group_stats[t]["Points"], group_stats[t]["Points For"], season_pts.get(t, 0), t),
        reverse=True
    )

    standings_rows = []
    for idx, name in enumerate(sorted_teams, 1):
        st_data = group_stats[name]
        status = "🟢 Qualifies" if idx <= 8 else "🔴 Risk of Elimination"
        standings_rows.append({
            "Rank": idx, "Status": status, "Team Name": name,
            "Number of games played": st_data["Played"],
            "Wins": st_data["Wins"], "Draws": st_data["Draws"], "Losses": st_data["Losses"],
            "Points For": st_data["Points For"], "Points": st_data["Points"]
        })

    df_standings = pd.DataFrame(standings_rows)
    df_results = pd.DataFrame(results_data)
    top_8 = sorted_teams[:8]

    # 2. Knockout Engine
    def run_knockout_series(team_a, team_b, matchdays, et_gw, is_unlocked):
        score_a, score_b = 0, 0
        records = []
        played_games = 0
        for gw in matchdays:
            is_active = (gw in started_gws or gw in finished_gws) and is_unlocked
            pa = scores.get(team_a, {}).get(gw, 0) if is_active else 0
            pb = scores.get(team_b, {}).get(gw, 0) if is_active else 0
            if is_active:
                played_games += 1
                if pa > pb: score_a += 1; ga, gb = 1, 0
                elif pb > pa: score_b += 1; ga, gb = 0, 1
                else: ga, gb = 0, 0
            else: ga, gb = "-", "-"
            records.append({
                "GW": f"GW {gw}", "Team A Name": team_a, "Team A Pts": pa if is_active else "-",
                "Team A Score": ga, "Team B Score": gb, "Team B Pts": pb if is_active else "-", "Team B Name": team_b
            })

        # Extra Time (Only displayed if needed)
        if (played_games == len(matchdays)) and (score_a == score_b):
            is_et_active = (et_gw in started_gws or et_gw in finished_gws) and is_unlocked
            pa_et = scores.get(team_a, {}).get(et_gw, 0) if is_et_active else 0
            pb_et = scores.get(team_b, {}).get(et_gw, 0) if is_et_active else 0
            if is_et_active:
                if pa_et >= pb_et: score_a += 1; ga_et, gb_et = 1, 0
                else: score_b += 1; ga_et, gb_et = 0, 1
            else: ga_et, gb_et = "-", "-"
            records.append({
                "GW": f"GW {et_gw} (ET)", "Team A Name": team_a, "Team A Pts": pa_et if is_et_active else "-",
                "Team A Score": ga_et, "Team B Score": gb_et, "Team B Pts": pb_et if is_et_active else "-", "Team B Name": team_b
            })

        winner = team_a if score_a >= score_b else team_b
        return winner, pd.DataFrame(records)

    qf_unlocked = 18 in finished_gws
    sf_unlocked = 23 in finished_gws
    final_unlocked = 30 in finished_gws

    # Quarter-Finals
    qf_pairs = [
        (top_8[7] if qf_unlocked else "8th Place", top_8[0] if qf_unlocked else "1st Place", "A"),
        (top_8[4] if qf_unlocked else "5th Place", top_8[3] if qf_unlocked else "4th Place", "B"),
        (top_8[5] if qf_unlocked else "6th Place", top_8[2] if qf_unlocked else "3rd Place", "C"),
        (top_8[6] if qf_unlocked else "7th Place", top_8[1] if qf_unlocked else "2nd Place", "D")
    ]
    winners_qf, qf_blocks = {}, []
    for t_a, t_b, code in qf_pairs:
        winner, df_series = run_knockout_series(t_a, t_b, [22, 23], 24, qf_unlocked)
        winners_qf[code] = winner if qf_unlocked else f"Winner of Tie {code}"
        qf_blocks.append(f"<div class='match-header'>Tie {code}: {t_a} vs {t_b}</div>" + df_series.to_html(index=False, classes="fl-table"))

    # Semi-Finals
    sf_pairs = [
        (winners_qf["A"], winners_qf["C"], "X"),
        (winners_qf["B"], winners_qf["D"], "Y")
    ]
    winners_sf, sf_blocks = {}, []
    for t_a, t_b, code in sf_pairs:
        winner, df_series = run_knockout_series(t_a, t_b, [27, 28, 29, 30], 31, sf_unlocked)
        winners_sf[code] = winner if sf_unlocked else f"Winner of Semi-Final {code}"
        sf_blocks.append(f"<div class='match-header'>Semi-Final {code}: {t_a} vs {t_b}</div>" + df_series.to_html(index=False, classes="fl-table"))

    # Final
    final_winner, df_final = run_knockout_series(winners_sf["X"], winners_sf["Y"], [34, 35, 36, 37], 38, final_unlocked)
    is_final_complete = final_unlocked and (37 in finished_gws or 38 in finished_gws)
    display_winner = final_winner if is_final_complete else "????"

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Complete HTML Template with 30s Auto-Refresh
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="30">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Craft & Draft Champions League</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            background: #ffffff;
            color: #212529;
            margin: 0;
            padding: 16px;
        }}
        .header-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #007bff;
            padding-bottom: 8px;
            margin-bottom: 20px;
        }}
        h1 {{ font-size: 24px; margin: 0; color: #1a1a1a; }}
        .live-badge {{
            background: #e3f2fd;
            color: #0d47a1;
            font-size: 12px;
            font-weight: 600;
            padding: 4px 8px;
            border-radius: 4px;
        }}
        h2 {{ font-size: 20px; margin-top: 30px; margin-bottom: 12px; color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
        h3 {{ font-size: 16px; margin-top: 18px; margin-bottom: 8px; color: #34495e; }}
        .match-header {{ font-weight: 600; font-size: 14px; margin-top: 15px; margin-bottom: 6px; color: #495057; }}
        
        /* Table Styles */
        .table-wrapper {{ overflow-x: auto; margin-bottom: 20px; }}
        .fl-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }}
        .fl-table th, .fl-table td {{
            padding: 8px 12px;
            border: 1px solid #dee2e6;
        }}
        .fl-table th {{
            background-color: #f8f9fa;
            font-weight: 600;
            color: #495057;
        }}
        .fl-table tr:nth-child(even) {{ background-color: #fcfcfc; }}
        
        .scrollable-box {{
            max-height: 420px;
            overflow-y: auto;
            border: 1px solid #dee2e6;
            margin-bottom: 25px;
        }}
        
        /* Stand-alone Winner Callout at the Very Bottom */
        .winner-box {{
            background: #d4edda;
            border: 2px solid #c3e6cb;
            color: #155724;
            padding: 16px;
            border-radius: 8px;
            font-size: 18px;
            font-weight: bold;
            text-align: center;
            margin-top: 35px;
            margin-bottom: 15px;
        }}
    </style>
</head>
<body>

    <div class="header-bar">
        <h1>Craft & Draft Champions League Group Phase</h1>
        <div class="live-badge">⚡ Auto-refreshes every 30s | Updated: {now_str}</div>
    </div>

    <h2>Group Phase Standings</h2>
    <div class="table-wrapper">
        {df_standings.to_html(index=False, classes="fl-table", escape=False)}
    </div>

    <h2>C&D CL Group Phase Fixtures and Results</h2>
    <div class="scrollable-box">
        {df_results.to_html(index=False, classes="fl-table")}
    </div>

    <h2>🏆 Knockout</h2>

    <h3>Quarter-Finals (Round 2)</h3>
    {''.join(qf_blocks)}

    <h3>Semi-Finals (Round 3)</h3>
    {''.join(sf_blocks)}

    <h3>🏆 Champions League Final</h3>
    <div class="match-header">Final: {winners_sf['X']} vs {winners_sf['Y']}</div>
    <div class="table-wrapper">
        {df_final.to_html(index=False, classes="fl-table")}
    </div>

    <div class="winner-box">
        🥇 Craft and Draft Champions League Winner: {display_winner}
    </div>

</body>
</html>"""
    return html


if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    html_output = generate_html()
    with open("docs/champions_league.html", "w", encoding="utf-8") as f:
        f.write(html_output)
    print("champions_league.html generated successfully in docs/")
