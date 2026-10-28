"""
AnalyticsBot Main Orchestration & Daemon Entrypoint.

Monitors upcoming NBA games for 4 specific high-volume 3-point shooters:
1. Stephen Curry (ID: "201939") – Team: GSW
2. Luka Dončić (ID: "1629029") – Team: DAL
3. LaMelo Ball (ID: "1630163") – Team: CHA
4. Donovan Mitchell (ID: "1628378") – Team: CLE

Gathers recent performance and opponent defensive metrics, calculates projected 3PM
using the weighted quantitative formula, and dispatches formatted memos to WhatsApp.

Compatible with PM2:
    pm2 start bot.py --name "analytics-bot" --interpreter python -- --daemon
"""

import sys
import os

# Ensure UTF-8 output encoding on all platforms (especially Windows console/PM2)
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import signal
import logging
import argparse
from datetime import datetime
from typing import List, Optional

import schedule

import config
from nba_client import NBAClient
from projection_engine import ProjectionEngine, ProjectionResult
from formatter import format_whatsapp_memo
from dispatcher import WhatsAppDispatcher

# Configure logging with UTF-8 safe output
class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
                stream.write(safe_msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        SafeStreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("AnalyticsBot")


class AnalyticsBot:
    """Core coordinator for AnalyticsBot pipeline."""

    def __init__(
        self,
        mock_mode: bool = False,
        dispatch_mode: Optional[str] = None,
        recipient_phone: Optional[str] = None,
    ):
        self.mock_mode = mock_mode
        self.client = NBAClient(mock_mode=mock_mode)
        self.engine = ProjectionEngine()
        self.dispatcher = WhatsAppDispatcher(
            mode=dispatch_mode,
            recipient_phone=recipient_phone,
        )

    def run_slate_analysis(
        self,
        target_date: Optional[str] = None,
        player_id_filter: Optional[str] = None,
    ) -> List[ProjectionResult]:
        """
        Executes a complete analysis run for a given date slate:
        1. Query scoreboard for target player teams
        2. Pull game logs and compute player breakdown
        3. Pull defensive context for opponent
        4. Calculate projected 3PM and lean
        5. Format and dispatch memos to WhatsApp
        """
        run_date = target_date or datetime.now().strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info("Starting AnalyticsBot slate analysis for date: %s", run_date)
        logger.info("=" * 60)

        # 1. Daily Matchup Detection
        matchups = self.client.get_daily_matchups(game_date=run_date)

        if player_id_filter:
            matchups = [m for m in matchups if m["player_id"] == player_id_filter]

        if not matchups:
            logger.info(
                "No target players (GSW, DAL, CHA, CLE) are scheduled to play on %s.",
                run_date,
            )
            return []

        logger.info("Found %d active target matchup(s) for today.", len(matchups))
        results: List[ProjectionResult] = []

        # 2-4. Process each player
        for item in matchups:
            p_id = item["player_id"]
            p_name = item["player_name"]
            p_team = item["team"]
            opp = item["opponent"]
            is_home = item["is_home"]
            line = item.get("consensus_line", config.DEFAULT_CONSENSUS_LINE)

            logger.info("--- Processing %s (%s vs %s) ---", p_name, p_team, opp)

            try:
                # 2. Statistical Data Retrieval
                logs_df = self.client.get_player_game_logs(player_id=p_id)
                player_breakdown = self.engine.compute_player_breakdown(
                    player_id=p_id,
                    player_name=p_name,
                    team=p_team,
                    opponent=opp,
                    is_home=is_home,
                    game_logs_df=logs_df,
                )

                # 3. Matchup & Defensive Context
                opp_context = self.client.get_opponent_context(opponent_abbr=opp)

                # 4. Projection Engine Logic
                proj_result = self.engine.project(
                    player_stats=player_breakdown,
                    opp_context=opp_context,
                    consensus_line=line,
                )
                results.append(proj_result)

                # 5. WhatsApp Message Formatting & Dispatch
                memo = format_whatsapp_memo(proj_result)
                logger.info("Dispatching analytical memo for %s...", p_name)
                dispatch_success = self.dispatcher.send_message(memo)

                if dispatch_success:
                    logger.info("Successfully delivered memo for %s.", p_name)
                else:
                    logger.warning("Failed to deliver memo for %s.", p_name)

            except Exception as exc:
                logger.error(
                    "Error processing analytics for player %s (ID %s): %s",
                    p_name,
                    p_id,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "AnalyticsBot analysis cycle complete. %d memo(s) generated.", len(results)
        )
        return results


def start_scheduler_daemon(bot: AnalyticsBot, run_time: str = config.SCHEDULE_TIME):
    """
    Schedules daily execution of AnalyticsBot and keeps the process alive
    for process managers like PM2 or systemd.
    """
    logger.info("Registering daily scheduler task at %s daily...", run_time)

    def job():
        try:
            logger.info("Triggered scheduled daily run at %s", datetime.now().isoformat())
            bot.run_slate_analysis()
        except Exception as exc:
            logger.error("Error during scheduled run: %s", exc, exc_info=True)

    schedule.every().day.at(run_time).do(job)

    # Graceful shutdown handler for PM2 signals (SIGINT, SIGTERM)
    stop_signal_received = False

    def handle_exit(signum, frame):
        nonlocal stop_signal_received
        logger.info("Received termination signal (%s). Shutting down AnalyticsBot daemon gracefully...", signum)
        stop_signal_received = True

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    logger.info("AnalyticsBot daemon is running and waiting for scheduled tasks. (Press Ctrl+C to stop)")

    while not stop_signal_received:
        schedule.run_pending()
        time.sleep(config.POLL_INTERVAL_SECONDS)

    logger.info("Daemon stopped.")


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="AnalyticsBot: NBA 3P Prop Intel & Notification Bot"
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run analysis immediately for current or specified date",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date for slate evaluation (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--player",
        type=str,
        default=None,
        help="Filter run to a specific player ID (e.g. '201939' for Curry)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic mock data fixtures for offline testing",
    )
    parser.add_argument(
        "--dry-run",
        "--console",
        action="store_true",
        dest="dry_run",
        help="Force console output without calling external WhatsApp endpoints",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a persistent daemon scheduled daily (for PM2 / background service)",
    )
    parser.add_argument(
        "--time",
        type=str,
        default=config.SCHEDULE_TIME,
        help=f"Daily schedule time in HH:MM format (default: {config.SCHEDULE_TIME})",
    )

    args = parser.parse_args()

    dispatch_mode = "console" if args.dry_run else None
    bot = AnalyticsBot(mock_mode=args.mock, dispatch_mode=dispatch_mode)

    # If --run-now or specific date is requested
    if args.run_now or args.date:
        bot.run_slate_analysis(target_date=args.date, player_id_filter=args.player)
        if not args.daemon:
            return

    # If --daemon is specified or no specific immediate flag was provided
    if args.daemon or (not args.run_now and not args.date):
        # In daemon mode, if launched without run-now, run the daily scheduler
        start_scheduler_daemon(bot, run_time=args.time)


if __name__ == "__main__":
    main()
