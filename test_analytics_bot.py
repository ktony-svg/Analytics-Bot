"""
Unit and Integration Tests for AnalyticsBot.

Covers:
1. Projection Engine base formula & H2H fallback logic
2. Matchup modifiers (Pace factor, Steal penalty, Perimeter defense penalty/boost)
3. Over/Under lean resolution
4. WhatsApp message format adherence
5. Webhook & Cloud API Dispatcher logic
6. Scoreboard matchup detection
"""

import unittest
from unittest.mock import patch, MagicMock
import pandas as pd

import config
from projection_engine import (
    ProjectionEngine,
    PlayerStatsBreakdown,
    OpponentDefensiveContext,
    ProjectionResult,
)
from formatter import format_whatsapp_memo
from dispatcher import WhatsAppDispatcher
from nba_client import NBAClient


class TestProjectionEngine(unittest.TestCase):
    """Test suite for the quantitative 3PM projection model."""

    def setUp(self):
        self.engine = ProjectionEngine(
            weight_season=0.50,
            weight_last_5=0.30,
            weight_h2h=0.20,
            league_avg_pace=99.5,
            steal_penalty_threshold=5,
            steal_penalty_pct=0.07,
            perimeter_top_threshold=5,
            perimeter_top_penalty_pct=0.08,
            perimeter_bottom_threshold=26,
            perimeter_bottom_boost_pct=0.08,
        )

    def test_base_formula_calculation(self):
        """
        Verify: Weighted 3PM = (0.50 * Season) + (0.30 * L5) + (0.20 * H2H).
        Example: Season=4.0, L5=5.0, H2H=6.0 -> 2.0 + 1.5 + 1.2 = 4.7
        """
        stats = PlayerStatsBreakdown(
            player_id="201939",
            player_name="Stephen Curry",
            team="GSW",
            opponent="LAL",
            is_home=True,
            season_avg_3pm=4.0,
            season_avg_3pa=10.0,
            season_3p_pct=0.400,
            l5_avg_3pm=5.0,
            l5_avg_3pa=11.0,
            h2h_games=3,
            h2h_avg_3pm=6.0,
            h2h_avg_3pa=12.0,
            h2h_used_fallback=False,
        )
        opp = OpponentDefensiveContext(
            opponent_team="LAL",
            pace=99.5,  # neutral pace
            pace_rank=15,
            opp_fg3_pct=0.360,
            opp_fg3_pct_rank=15,  # neutral defense
            opp_stl_pg=7.5,
            opp_stl_rank=15,  # neutral steals
        )

        res = self.engine.project(stats, opp, consensus_line=3.5)
        expected_base = (0.50 * 4.0) + (0.30 * 5.0) + (0.20 * 6.0)  # 4.7
        self.assertAlmostEqual(res.base_weighted_3pm, expected_base, places=2)
        self.assertAlmostEqual(res.projected_3pm, 4.7, places=1)
        self.assertEqual(res.lean, "OVER 3.5")

    def test_h2h_fallback_to_season_baseline(self):
        """If H2H games are 0, H2H should fall back to Season baseline."""
        logs = pd.DataFrame([
            {"GAME_DATE": "2024-10-25", "MATCHUP": "CHA vs. ATL", "MIN": 32, "FG3M": 5, "FG3A": 10, "FG3_PCT": 0.5},
            {"GAME_DATE": "2024-10-23", "MATCHUP": "CHA @ DET", "MIN": 30, "FG3M": 3, "FG3A": 10, "FG3_PCT": 0.3},
        ])
        breakdown = self.engine.compute_player_breakdown(
            player_id="1630163",
            player_name="LaMelo Ball",
            team="CHA",
            opponent="DEN",  # No matchup vs DEN in logs
            is_home=True,
            game_logs_df=logs,
        )

        self.assertEqual(breakdown.h2h_games, 0)
        self.assertTrue(breakdown.h2h_used_fallback)
        self.assertAlmostEqual(breakdown.h2h_avg_3pm, breakdown.season_avg_3pm)

    def test_pace_adjustment(self):
        """Opponent pace of 109.45 against 99.5 should scale by 1.10 (+10%)."""
        stats = PlayerStatsBreakdown(
            player_id="1628378",
            player_name="Donovan Mitchell",
            team="CLE",
            opponent="IND",
            is_home=True,
            season_avg_3pm=3.0,
            season_avg_3pa=8.0,
            l5_avg_3pm=3.0,
            l5_avg_3pa=8.0,
            h2h_avg_3pm=3.0,
            h2h_avg_3pa=8.0,
            h2h_games=2,
        )
        opp = OpponentDefensiveContext(
            opponent_team="IND",
            pace=109.45,
            pace_rank=2,
            opp_fg3_pct_rank=15,
            opp_stl_rank=15,
        )
        res = self.engine.project(stats, opp, consensus_line=3.5)
        expected_pace_factor = 109.45 / 99.5  # 1.10
        self.assertAlmostEqual(res.pace_factor, 1.10, places=2)
        expected_3pm = 3.0 * expected_pace_factor  # 3.3
        self.assertAlmostEqual(res.projected_3pm, round(expected_3pm, 1), places=1)

    def test_steal_penalty_for_top_5(self):
        """If opponent rank for steals is <= 5, reduce expected 3PM by 7%."""
        stats = PlayerStatsBreakdown(
            player_id="1630163",
            player_name="LaMelo Ball",
            team="CHA",
            opponent="MIA",
            is_home=True,
            season_avg_3pm=4.0,
            season_avg_3pa=10.0,
            l5_avg_3pm=4.0,
            l5_avg_3pa=10.0,
            h2h_avg_3pm=4.0,
            h2h_avg_3pa=10.0,
            h2h_games=1,
        )
        # Miami: Steal rank = 3 (Top 5)
        opp = OpponentDefensiveContext(
            opponent_team="MIA",
            pace=99.5,
            pace_rank=15,
            opp_fg3_pct_rank=15,
            opp_stl_rank=3,
        )
        res = self.engine.project(stats, opp, consensus_line=3.5)
        self.assertEqual(res.steal_modifier, -0.07)
        # Expected: 4.0 * (1 - 0.07) = 3.72 -> 3.7
        self.assertAlmostEqual(res.projected_3pm, 3.7, places=1)

    def test_perimeter_defense_top_and_bottom_modifiers(self):
        """
        Opponent top-5 lowest 3P% allowed -> -8% penalty.
        Opponent bottom-5 highest 3P% allowed (>=26) -> +8% boost.
        """
        stats = PlayerStatsBreakdown(
            player_id="1629029",
            player_name="Luka Dončić",
            team="DAL",
            opponent="MIN",
            is_home=False,
            season_avg_3pm=4.0,
            season_avg_3pa=10.0,
            l5_avg_3pm=4.0,
            l5_avg_3pa=10.0,
            h2h_avg_3pm=4.0,
            h2h_avg_3pa=10.0,
            h2h_games=2,
        )
        # Minnesota: Opponent 3P% Rank = 2 (Top 5 defense)
        opp_elite = OpponentDefensiveContext(
            opponent_team="MIN",
            pace=99.5,
            pace_rank=15,
            opp_fg3_pct_rank=2,
            opp_stl_rank=15,
        )
        res_elite = self.engine.project(stats, opp_elite, consensus_line=3.5)
        self.assertEqual(res_elite.perimeter_def_modifier, -0.08)
        self.assertAlmostEqual(res_elite.projected_3pm, round(4.0 * 0.92, 1), places=1)

        # Weak defense: Opponent 3P% Rank = 28 (Bottom 5)
        opp_weak = OpponentDefensiveContext(
            opponent_team="WAS",
            pace=99.5,
            pace_rank=15,
            opp_fg3_pct_rank=28,
            opp_stl_rank=15,
        )
        res_weak = self.engine.project(stats, opp_weak, consensus_line=3.5)
        self.assertEqual(res_weak.perimeter_def_modifier, 0.08)
        self.assertAlmostEqual(res_weak.projected_3pm, round(4.0 * 1.08, 1), places=1)


class TestMessageFormatting(unittest.TestCase):
    """Verify that generated memos adhere exactly to required structure."""

    def test_whatsapp_memo_format(self):
        stats = PlayerStatsBreakdown(
            player_id="201939",
            player_name="Stephen Curry",
            team="GSW",
            opponent="LAL",
            is_home=True,
            season_games=10,
            season_avg_3pm=4.8,
            season_avg_3pa=11.6,
            season_3p_pct=0.414,
            l5_games=5,
            l5_avg_3pm=5.2,
            l5_avg_3pa=12.0,
            h2h_games=4,
            h2h_avg_3pm=5.5,
            h2h_avg_3pa=13.0,
        )
        opp = OpponentDefensiveContext(
            opponent_team="LAL",
            pace=101.4,
            pace_rank=6,
            pace_category="Fast",
            opp_fg3_pct=0.376,
            opp_fg3_pct_rank=27,
            opp_stl_pg=7.4,
            opp_stl_rank=16,
            steal_threat_category="Moderate",
        )
        engine = ProjectionEngine()
        result = engine.project(stats, opp, consensus_line=3.5)
        memo = format_whatsapp_memo(result)

        # Check required headers and structural tokens
        self.assertIn("🏀 NBA 3P PROP INTEL | TONIGHT'S SLATE", memo)
        self.assertIn("Player: Stephen Curry (GSW vs. LAL)", memo)
        self.assertIn("Consensus Line: 3.5 3PM (O/U)", memo)
        self.assertIn("🎯 Model Projection:", memo)
        self.assertIn("Lean: OVER 3.5", memo)
        self.assertIn("📊 Statistical Breakdown:", memo)
        self.assertIn("• Season Baseline: 4.8 3PM on 11.6 attempts (41.4%)", memo)
        self.assertIn("• Recent Form (Last 5): 5.2 3PM on 12.0 attempts", memo)
        self.assertIn("• Head-to-Head History: 5.5 3PM over last 4 meetings", memo)
        self.assertIn("🛡️ Opponent Matchup Factors:", memo)
        self.assertIn("• Opponent Pace: Ranked #6 (Fast matchup pace)", memo)
        self.assertIn("• Perimeter Defense: Ranked #27 in 3P% allowed (37.6%)", memo)
        self.assertIn("• Steal Threat: Ranked #16 (Moderate perimeter disruption)", memo)
        self.assertIn("Verdict:", memo)


class TestDispatcher(unittest.TestCase):
    """Test suite for WhatsApp Dispatcher."""

    def test_console_dispatcher(self):
        disp = WhatsAppDispatcher(mode="console")
        success = disp.send_message("Test Message", "+1234567890")
        self.assertTrue(success)

    @patch("requests.post")
    def test_webhook_dispatcher_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status":"ok"}'
        mock_post.return_value = mock_resp

        disp = WhatsAppDispatcher(
            mode="webhook",
            webhook_url="http://localhost:3000/send",
            webhook_token="secret",
        )
        success = disp.send_message("Test Memo", "+1234567890")
        self.assertTrue(success)
        mock_post.assert_called_once()

    @patch("requests.get")
    def test_callmebot_dispatcher_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Message queued"
        mock_get.return_value = mock_resp

        disp = WhatsAppDispatcher(
            mode="callmebot",
            callmebot_api_key="123456",
        )
        success = disp.send_message("Test Memo", "+1234567890")
        self.assertTrue(success)
        mock_get.assert_called_once()

    @patch("requests.post")
    def test_cloud_api_dispatcher_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"messages":[{"id":"wamid.123"}]}'
        mock_post.return_value = mock_resp

        disp = WhatsAppDispatcher(
            mode="cloud",
            cloud_api_url="https://graph.facebook.com/v19.0",
            phone_number_id="123456789",
            cloud_access_token="test_token",
        )
        success = disp.send_message("Test Memo", "+1234567890")
        self.assertTrue(success)
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_telegram_dispatcher_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"ok":true}'
        mock_post.return_value = mock_resp

        disp = WhatsAppDispatcher(
            mode="telegram",
            telegram_bot_token="fake_bot_token",
            telegram_chat_id="123456789",
        )
        success = disp.send_message("Test Memo")
        self.assertTrue(success)
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_discord_dispatcher_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_post.return_value = mock_resp

        disp = WhatsAppDispatcher(
            mode="discord",
            discord_webhook_url="https://discord.com/api/webhooks/test",
        )
        success = disp.send_message("Test Memo")
        self.assertTrue(success)
        mock_post.assert_called_once()


class TestScoreboardMatchupDetection(unittest.TestCase):
    """Test ScoreboardV2 parsing logic for the 4 target teams."""

    def test_scoreboard_parsing(self):
        client = NBAClient(mock_mode=True)
        matchups = client.get_daily_matchups("2024-10-28")
        self.assertEqual(len(matchups), 4)
        player_names = [m["player_name"] for m in matchups]
        self.assertIn("Stephen Curry", player_names)
        self.assertIn("Luka Dončić", player_names)
        self.assertIn("LaMelo Ball", player_names)
        self.assertIn("Donovan Mitchell", player_names)


if __name__ == "__main__":
    unittest.main()
