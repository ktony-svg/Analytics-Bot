"""
Projection Engine Module for AnalyticsBot.

Calculates projected 3-pointers made (3PM) using a weighted quantitative formula,
pace adjustments, opponent defensive ranks, and provides an actionable lean.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

import config


@dataclass
class PlayerStatsBreakdown:
    """Statistical breakdown for a player."""
    player_id: str
    player_name: str
    team: str
    opponent: str
    is_home: bool

    # Season Baseline
    season_games: int = 0
    season_avg_3pm: float = 0.0
    season_avg_3pa: float = 0.0
    season_3p_pct: float = 0.0

    # Recent Form (Last 5 Games)
    l5_games: int = 0
    l5_avg_3pm: float = 0.0
    l5_avg_3pa: float = 0.0
    l5_3p_pct: float = 0.0

    # Head-to-Head (H2H)
    h2h_games: int = 0
    h2h_avg_3pm: float = 0.0
    h2h_avg_3pa: float = 0.0
    h2h_3p_pct: float = 0.0
    h2h_used_fallback: bool = False


@dataclass
class OpponentDefensiveContext:
    """Opponent defensive and pace metrics."""
    opponent_team: str
    pace: float = 99.5
    pace_rank: int = 15
    pace_category: str = "Average"  # "Fast" / "Slow" / "Neutral"

    opp_fg3_pct: float = 0.360  # e.g. 0.362 -> 36.2%
    opp_fg3_pct_rank: int = 15  # 1 = best defense (lowest 3P% allowed)

    opp_stl_pg: float = 7.5
    opp_stl_rank: int = 15  # 1 = most steals generated (highest turnover pressure)
    steal_threat_category: str = "Moderate"  # "High" / "Moderate" / "Low"


@dataclass
class ProjectionResult:
    """Comprehensive output of the projection model."""
    player_stats: PlayerStatsBreakdown
    opp_context: OpponentDefensiveContext
    consensus_line: float = 3.5

    # Intermediate calculations
    base_weighted_3pm: float = 0.0
    base_weighted_3pa: float = 0.0
    pace_factor: float = 1.0
    steal_modifier: float = 0.0
    perimeter_def_modifier: float = 0.0

    # Final outputs
    projected_3pm: float = 0.0
    projected_3pa: float = 0.0
    lean: str = "OVER 3.5"
    verdict: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProjectionEngine:
    """Quantitative projection engine for 3PM props."""

    def __init__(
        self,
        weight_season: float = config.WEIGHT_SEASON,
        weight_last_5: float = config.WEIGHT_LAST_5,
        weight_h2h: float = config.WEIGHT_H2H,
        league_avg_pace: float = config.LEAGUE_AVG_PACE,
        steal_penalty_threshold: int = config.STEAL_RANK_PENALTY_THRESHOLD,
        steal_penalty_pct: float = config.STEAL_RANK_PENALTY_PCT,
        perimeter_top_threshold: int = config.PERIMETER_DEF_TOP_THRESHOLD,
        perimeter_top_penalty_pct: float = config.PERIMETER_DEF_TOP_PENALTY_PCT,
        perimeter_bottom_threshold: int = config.PERIMETER_DEF_BOTTOM_THRESHOLD,
        perimeter_bottom_boost_pct: float = config.PERIMETER_DEF_BOTTOM_BOOST_PCT,
    ):
        self.w_season = weight_season
        self.w_l5 = weight_last_5
        self.w_h2h = weight_h2h
        self.league_avg_pace = league_avg_pace
        self.steal_penalty_threshold = steal_penalty_threshold
        self.steal_penalty_pct = steal_penalty_pct
        self.perimeter_top_threshold = perimeter_top_threshold
        self.perimeter_top_penalty_pct = perimeter_top_penalty_pct
        self.perimeter_bottom_threshold = perimeter_bottom_threshold
        self.perimeter_bottom_boost_pct = perimeter_bottom_boost_pct

    def compute_player_breakdown(
        self,
        player_id: str,
        player_name: str,
        team: str,
        opponent: str,
        is_home: bool,
        game_logs_df: pd.DataFrame,
    ) -> PlayerStatsBreakdown:
        """
        Parses full-season game logs and computes Season Baseline,
        Recent Form (last 5 games), and H2H against opponent.
        """
        breakdown = PlayerStatsBreakdown(
            player_id=player_id,
            player_name=player_name,
            team=team,
            opponent=opponent,
            is_home=is_home,
        )

        if game_logs_df.empty:
            return breakdown

        # Ensure correct column types
        df = game_logs_df.copy()
        for col in ["FG3M", "FG3A", "FG3_PCT", "MIN"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # 1. Season Baseline
        breakdown.season_games = len(df)
        breakdown.season_avg_3pm = float(df["FG3M"].mean()) if not df.empty else 0.0
        breakdown.season_avg_3pa = float(df["FG3A"].mean()) if not df.empty else 0.0
        total_3pm = float(df["FG3M"].sum()) if not df.empty else 0.0
        total_3pa = float(df["FG3A"].sum()) if not df.empty else 0.0
        breakdown.season_3p_pct = (total_3pm / total_3pa) if total_3pa > 0 else 0.0

        # 2. Recent Form (Last 5 Games)
        # Note: PlayerGameLog is sorted chronologically descending by default (most recent first)
        last_5_df = df.head(5)
        breakdown.l5_games = len(last_5_df)
        breakdown.l5_avg_3pm = float(last_5_df["FG3M"].mean()) if not last_5_df.empty else breakdown.season_avg_3pm
        breakdown.l5_avg_3pa = float(last_5_df["FG3A"].mean()) if not last_5_df.empty else breakdown.season_avg_3pa
        l5_total_3pm = float(last_5_df["FG3M"].sum()) if not last_5_df.empty else 0.0
        l5_total_3pa = float(last_5_df["FG3A"].sum()) if not last_5_df.empty else 0.0
        breakdown.l5_3p_pct = (l5_total_3pm / l5_total_3pa) if l5_total_3pa > 0 else breakdown.season_3p_pct

        # 3. Head-to-Head (H2H) Filter by Opponent Abbreviation
        # Matchup format in NBA API is usually "GSW vs. LAL" or "GSW @ LAL"
        opp_clean = opponent.strip().upper()
        h2h_mask = df["MATCHUP"].str.contains(rf"\b{opp_clean}\b", case=False, na=False)
        h2h_df = df[h2h_mask]

        if not h2h_df.empty:
            breakdown.h2h_games = len(h2h_df)
            breakdown.h2h_avg_3pm = float(h2h_df["FG3M"].mean())
            breakdown.h2h_avg_3pa = float(h2h_df["FG3A"].mean())
            h2h_total_3pm = float(h2h_df["FG3M"].sum())
            h2h_total_3pa = float(h2h_df["FG3A"].sum())
            breakdown.h2h_3p_pct = (h2h_total_3pm / h2h_total_3pa) if h2h_total_3pa > 0 else breakdown.season_3p_pct
            breakdown.h2h_used_fallback = False
        else:
            # Fall back to season baseline if no H2H meetings yet
            breakdown.h2h_games = 0
            breakdown.h2h_avg_3pm = breakdown.season_avg_3pm
            breakdown.h2h_avg_3pa = breakdown.season_avg_3pa
            breakdown.h2h_3p_pct = breakdown.season_3p_pct
            breakdown.h2h_used_fallback = True

        return breakdown

    def project(
        self,
        player_stats: PlayerStatsBreakdown,
        opp_context: OpponentDefensiveContext,
        consensus_line: Optional[float] = None,
    ) -> ProjectionResult:
        """
        Executes the weighted quantitative formula and context modifiers.
        """
        if consensus_line is None:
            consensus_line = config.DEFAULT_CONSENSUS_LINE

        # Base Formula:
        # Weighted 3PM = (0.50 * Season Avg 3PM) + (0.30 * Last 5 Games Avg 3PM) + (0.20 * H2H Avg 3PM)
        h2h_3pm = player_stats.h2h_avg_3pm
        base_weighted_3pm = (
            (self.w_season * player_stats.season_avg_3pm)
            + (self.w_l5 * player_stats.l5_avg_3pm)
            + (self.w_h2h * h2h_3pm)
        )

        h2h_3pa = player_stats.h2h_avg_3pa
        base_weighted_3pa = (
            (self.w_season * player_stats.season_avg_3pa)
            + (self.w_l5 * player_stats.l5_avg_3pa)
            + (self.w_h2h * h2h_3pa)
        )

        # Matchup Modifiers:
        # 1. Pace Adjustment: Scale attempts by (Opponent Pace / League Average Pace [99.5])
        pace_factor = (
            (opp_context.pace / self.league_avg_pace)
            if self.league_avg_pace > 0
            else 1.0
        )
        scaled_3pa = base_weighted_3pa * pace_factor
        pace_adjusted_3pm = base_weighted_3pm * pace_factor

        # 2. Steal / Deflection Penalty:
        # If opponent rank for steals is top 5, reduce expected 3PM by 7%
        if 1 <= opp_context.opp_stl_rank <= self.steal_penalty_threshold:
            steal_modifier = -self.steal_penalty_pct
        else:
            steal_modifier = 0.0

        # 3. Perimeter Defense Penalty / Boost:
        # If opponent is top-5 in lowest 3P% allowed, reduce expected 3PM by 8%
        # If bottom-5 (rank >= 26), increase expected 3PM by 8%
        if 1 <= opp_context.opp_fg3_pct_rank <= self.perimeter_top_threshold:
            perimeter_def_modifier = -self.perimeter_top_penalty_pct
        elif opp_context.opp_fg3_pct_rank >= self.perimeter_bottom_threshold:
            perimeter_def_modifier = self.perimeter_bottom_boost_pct
        else:
            perimeter_def_modifier = 0.0

        # Composite context modifier
        combined_def_factor = 1.0 + steal_modifier + perimeter_def_modifier
        final_projected_3pm = max(0.0, pace_adjusted_3pm * combined_def_factor)

        # Over / Under Lean
        if final_projected_3pm > consensus_line:
            lean = f"OVER {consensus_line}"
        elif final_projected_3pm < consensus_line:
            lean = f"UNDER {consensus_line}"
        else:
            lean = f"PUSH {consensus_line}"

        # Generate insightful verdict rationale
        verdict = self._generate_verdict(
            player_stats=player_stats,
            opp_context=opp_context,
            base_3pm=base_weighted_3pm,
            final_3pm=final_projected_3pm,
            consensus_line=consensus_line,
            pace_factor=pace_factor,
            steal_mod=steal_modifier,
            perim_mod=perimeter_def_modifier,
            lean=lean,
        )

        return ProjectionResult(
            player_stats=player_stats,
            opp_context=opp_context,
            consensus_line=consensus_line,
            base_weighted_3pm=round(base_weighted_3pm, 2),
            base_weighted_3pa=round(base_weighted_3pa, 2),
            pace_factor=round(pace_factor, 3),
            steal_modifier=round(steal_modifier, 3),
            perimeter_def_modifier=round(perimeter_def_modifier, 3),
            projected_3pm=round(final_projected_3pm, 1),
            projected_3pa=round(scaled_3pa, 1),
            lean=lean,
            verdict=verdict,
            metadata={
                "combined_def_factor": round(combined_def_factor, 3),
                "raw_projected_3pm": final_projected_3pm,
            },
        )

    def _generate_verdict(
        self,
        player_stats: PlayerStatsBreakdown,
        opp_context: OpponentDefensiveContext,
        base_3pm: float,
        final_3pm: float,
        consensus_line: float,
        pace_factor: float,
        steal_mod: float,
        perim_mod: float,
        lean: str,
    ) -> str:
        """Constructs an executive analytical rationale for the verdict."""
        reasons = []

        # Form commentary
        if player_stats.l5_avg_3pm > player_stats.season_avg_3pm + 0.3:
            reasons.append(
                f"surging recent volume ({player_stats.l5_avg_3pm:.1f} 3PM over last 5)"
            )
        elif player_stats.l5_avg_3pm < player_stats.season_avg_3pm - 0.3:
            reasons.append(
                f"cooling recent clip ({player_stats.l5_avg_3pm:.1f} 3PM over last 5)"
            )

        # Pace commentary
        if pace_factor > 1.01:
            pace_pct = (pace_factor - 1.0) * 100
            reasons.append(f"an elevated matchup pace (+{pace_pct:.1f}% expected possessions)")
        elif pace_factor < 0.99:
            pace_pct = (1.0 - pace_factor) * 100
            reasons.append(f"a sluggish game pace (-{pace_pct:.1f}% possessions)")

        # Perimeter defense commentary
        if perim_mod > 0:
            reasons.append(
                f"a favorable matchup against {opp_context.opponent_team}'s porous perimeter defense "
                f"(ranked #{opp_context.opp_fg3_pct_rank} in 3P% allowed)"
            )
        elif perim_mod < 0:
            reasons.append(
                f"a stiff perimeter test against {opp_context.opponent_team}'s elite defense "
                f"(ranked #{opp_context.opp_fg3_pct_rank} allowing {opp_context.opp_fg3_pct * 100:.1f}%)"
            )

        # Steal threat commentary
        if steal_mod < 0:
            reasons.append(
                f"heightened deflection and turnover risk against a top-5 steal unit (Rank #{opp_context.opp_stl_rank})"
            )

        # Head-to-head note
        if not player_stats.h2h_used_fallback and player_stats.h2h_games > 0:
            if player_stats.h2h_avg_3pm >= consensus_line + 0.5:
                reasons.append(
                    f"dominant historical success vs {opp_context.opponent_team} ({player_stats.h2h_avg_3pm:.1f} 3PM avg)"
                )
            elif player_stats.h2h_avg_3pm <= consensus_line - 0.5:
                reasons.append(
                    f"historical struggles vs {opp_context.opponent_team} ({player_stats.h2h_avg_3pm:.1f} 3PM avg)"
                )

        if not reasons:
            reasons.append("steady baseline metrics aligned with standard situational factors")

        reasons_text = ", combined with ".join(reasons)
        diff = final_3pm - consensus_line

        if "OVER" in lean:
            summary = (
                f"Projected {final_3pm:.1f} 3PM clears the {consensus_line} line by {diff:+.1f} makes, "
                f"underpinned by {reasons_text}. Strong value on the OVER."
            )
        else:
            summary = (
                f"Projected {final_3pm:.1f} 3PM sits {abs(diff):.1f} makes below the {consensus_line} total due to "
                f"{reasons_text}. Situational model clearly signals the UNDER."
            )

        return summary
