"""
WhatsApp Message Formatter Module for AnalyticsBot.

Converts quantitative projection models and contextual stats into
executive sports analytics memos adhering to the specified format.
"""

from projection_engine import ProjectionResult


def format_whatsapp_memo(result: ProjectionResult) -> str:
    """
    Formats a single player's projection result into the required executive memo.
    """
    stats = result.player_stats
    opp = result.opp_context

    matchup_separator = "vs." if stats.is_home else "@"
    # Matchup indicator: e.g. GSW vs. LAL or GSW @ BOS
    matchup_str = f"{stats.team} {matchup_separator} {stats.opponent}"

    # Determine pace qualitative tag
    if opp.pace_category:
        pace_label = opp.pace_category
    else:
        if opp.pace_rank <= 10 or opp.pace >= 101.0:
            pace_label = "Fast"
        elif opp.pace_rank >= 21 or opp.pace <= 98.0:
            pace_label = "Slow"
        else:
            pace_label = "Moderate"

    # Determine steal qualitative tag
    if opp.steal_threat_category:
        steal_label = opp.steal_threat_category
    else:
        if opp.opp_stl_rank <= 10:
            steal_label = "High"
        elif opp.opp_stl_rank >= 21:
            steal_label = "Low"
        else:
            steal_label = "Moderate"

    # Head-to-Head representation
    if stats.h2h_games > 0:
        h2h_str = f"{stats.h2h_avg_3pm:.1f} 3PM over last {stats.h2h_games} meetings"
    else:
        h2h_str = f"{stats.h2h_avg_3pm:.1f} 3PM over last 0 meetings (Season baseline)"

    memo = (
        "🏀 NBA 3P PROP INTEL | TONIGHT'S SLATE\n\n"
        f"Player: {stats.player_name} ({matchup_str})\n"
        f"Consensus Line: {result.consensus_line:.1f} 3PM (O/U)\n\n"
        f"🎯 Model Projection: {result.projected_3pm:.1f} 3PM (Lean: {result.lean})\n\n"
        "📊 Statistical Breakdown:\n"
        f"• Season Baseline: {stats.season_avg_3pm:.1f} 3PM on {stats.season_avg_3pa:.1f} attempts ({stats.season_3p_pct * 100:.1f}%)\n"
        f"• Recent Form (Last 5): {stats.l5_avg_3pm:.1f} 3PM on {stats.l5_avg_3pa:.1f} attempts\n"
        f"• Head-to-Head History: {h2h_str}\n\n"
        "🛡️ Opponent Matchup Factors:\n"
        f"• Opponent Pace: Ranked #{opp.pace_rank} ({pace_label} matchup pace)\n"
        f"• Perimeter Defense: Ranked #{opp.opp_fg3_pct_rank} in 3P% allowed ({opp.opp_fg3_pct * 100:.1f}%)\n"
        f"• Steal Threat: Ranked #{opp.opp_stl_rank} ({steal_label} perimeter disruption)\n\n"
        f"Verdict: {result.verdict}"
    )

    return memo
