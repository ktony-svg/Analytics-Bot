"""
AnalyticsBot Configuration Module.

Defines target players, quantitative model constants, API settings,
and environment-based WhatsApp dispatch configurations.
"""

import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# =====================================================================
# Target Players & Metadata
# =====================================================================
TARGET_PLAYERS: Dict[str, Dict[str, Any]] = {
    "201939": {
        "id": "201939",
        "name": "Stephen Curry",
        "team": "GSW",
        "default_consensus_line": 3.5,
    },
    "1629029": {
        "id": "1629029",
        "name": "Luka Dončić",
        "team": "DAL",
        "default_consensus_line": 3.5,
    },
    "1630163": {
        "id": "1630163",
        "name": "LaMelo Ball",
        "team": "CHA",
        "default_consensus_line": 3.5,
    },
    "1628378": {
        "id": "1628378",
        "name": "Donovan Mitchell",
        "team": "CLE",
        "default_consensus_line": 3.5,
    },
}

# Quick lookup by team abbreviation
TARGET_TEAMS: set[str] = {p["team"] for p in TARGET_PLAYERS.values()}

# =====================================================================
# Quantitative Model Parameters
# =====================================================================
# Base formula weights
WEIGHT_SEASON: float = 0.50
WEIGHT_LAST_5: float = 0.30
WEIGHT_H2H: float = 0.20

# Matchup modifiers
LEAGUE_AVG_PACE: float = float(os.getenv("LEAGUE_AVG_PACE", "99.5"))

# Steal / Deflection Penalty
STEAL_RANK_PENALTY_THRESHOLD: int = int(os.getenv("STEAL_RANK_PENALTY_THRESHOLD", "5"))
STEAL_RANK_PENALTY_PCT: float = float(os.getenv("STEAL_RANK_PENALTY_PCT", "0.07"))  # -7%

# Perimeter Defense Penalty / Boost
# Top-5 lowest 3P% allowed -> defensive penalty (-8%)
PERIMETER_DEF_TOP_THRESHOLD: int = int(os.getenv("PERIMETER_DEF_TOP_THRESHOLD", "5"))
PERIMETER_DEF_TOP_PENALTY_PCT: float = float(os.getenv("PERIMETER_DEF_TOP_PENALTY_PCT", "0.08"))

# Bottom-5 highest 3P% allowed (ranks 26-30) -> defense boost (+8%)
PERIMETER_DEF_BOTTOM_THRESHOLD: int = int(os.getenv("PERIMETER_DEF_BOTTOM_THRESHOLD", "26"))
PERIMETER_DEF_BOTTOM_BOOST_PCT: float = float(os.getenv("PERIMETER_DEF_BOTTOM_BOOST_PCT", "0.08"))

# Default consensus line
DEFAULT_CONSENSUS_LINE: float = float(os.getenv("DEFAULT_CONSENSUS_LINE", "3.5"))

# =====================================================================
# WhatsApp Dispatch Settings
# =====================================================================
WHATSAPP_DISPATCH_MODE: str = os.getenv("WHATSAPP_DISPATCH_MODE", "console").lower()
WHATSAPP_WEBHOOK_URL: str = os.getenv("WHATSAPP_WEBHOOK_URL", "http://localhost:3000/api/send-message")
WHATSAPP_WEBHOOK_AUTH_TOKEN: str = os.getenv("WHATSAPP_WEBHOOK_AUTH_TOKEN", "")

WHATSAPP_CLOUD_API_URL: str = os.getenv("WHATSAPP_CLOUD_API_URL", "https://graph.facebook.com/v19.0")
WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_RECIPIENT_PHONE: str = os.getenv("WHATSAPP_RECIPIENT_PHONE", "+1234567890")

# --- CallMeBot Free Gateway Settings ---
CALLMEBOT_API_KEY: str = os.getenv("CALLMEBOT_API_KEY", "")

# --- Instant No-Card Cloud Alerts: Telegram & Discord ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

# =====================================================================
# Scheduler Settings
# =====================================================================
SCHEDULE_TIME: str = os.getenv("SCHEDULE_TIME", "09:00")
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))

# =====================================================================
# NBA API Settings & Headers
# =====================================================================
NBA_API_TIMEOUT_SECONDS: int = int(os.getenv("NBA_API_TIMEOUT_SECONDS", "30"))
NBA_API_RETRY_COUNT: int = int(os.getenv("NBA_API_RETRY_COUNT", "3"))
NBA_API_DELAY_BETWEEN_CALLS: float = float(os.getenv("NBA_API_DELAY_BETWEEN_CALLS", "1.0"))

# Default to None so nba_api uses its built-in tuned headers
NBA_API_HEADERS: Optional[Dict[str, str]] = None
