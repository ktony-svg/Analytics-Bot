"""
WhatsApp Dispatcher Module for AnalyticsBot.

Provides a pluggable dispatch layer to send analytical memos via:
1. Local/Microservice Webhook (e.g., Baileys / whatsapp-web.js HTTP bridge)
2. WhatsApp Cloud API (Official Meta Graph API)
3. Console / Dry-run logger (for development, staging, or CI/CD)
"""

import json
import logging
import sys
from typing import Dict, Any, Optional
import requests

import config

logger = logging.getLogger("AnalyticsBot.Dispatcher")


class WhatsAppDispatcher:
    """Pluggable dispatch client for delivering alerts to WhatsApp."""

    def __init__(
        self,
        mode: Optional[str] = None,
        recipient_phone: Optional[str] = None,
        webhook_url: Optional[str] = None,
        webhook_token: Optional[str] = None,
        cloud_api_url: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        cloud_access_token: Optional[str] = None,
        callmebot_api_key: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        discord_webhook_url: Optional[str] = None,
        timeout_seconds: int = 15,
    ):
        self.mode = (mode or config.WHATSAPP_DISPATCH_MODE).lower()
        self.recipient_phone = recipient_phone or config.WHATSAPP_RECIPIENT_PHONE
        self.webhook_url = webhook_url or config.WHATSAPP_WEBHOOK_URL
        self.webhook_token = webhook_token or config.WHATSAPP_WEBHOOK_AUTH_TOKEN
        self.cloud_api_url = cloud_api_url or config.WHATSAPP_CLOUD_API_URL
        self.phone_number_id = phone_number_id or config.WHATSAPP_PHONE_NUMBER_ID
        self.cloud_access_token = cloud_access_token or config.WHATSAPP_ACCESS_TOKEN
        self.callmebot_api_key = callmebot_api_key or config.CALLMEBOT_API_KEY
        self.telegram_bot_token = telegram_bot_token or config.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = telegram_chat_id or config.TELEGRAM_CHAT_ID
        self.discord_webhook_url = discord_webhook_url or config.DISCORD_WEBHOOK_URL
        self.timeout_seconds = timeout_seconds

    def send_message(self, message: str, recipient: Optional[str] = None) -> bool:
        """
        Dispatches a message using the configured mode.
        Returns True if successful, False otherwise.
        """
        target = recipient or self.recipient_phone

        if self.mode == "console":
            return self._dispatch_console(message, target)
        elif self.mode in ("webhook", "waha"):
            return self._dispatch_webhook(message, target)
        elif self.mode == "callmebot":
            return self._dispatch_callmebot(message, target)
        elif self.mode == "cloud":
            return self._dispatch_cloud_api(message, target)
        elif self.mode == "telegram":
            return self._dispatch_telegram(message, target)
        elif self.mode == "discord":
            return self._dispatch_discord(message)
        else:
            logger.warning(
                "Unknown dispatch mode '%s'. Defaulting to console output.", self.mode
            )
            return self._dispatch_console(message, target)

    def _dispatch_console(self, message: str, recipient: str) -> bool:
        """Prints message to stdout/logger with divider, safely handling any terminal encoding."""
        divider = "=" * 60
        output = (
            f"\n{divider}\n"
            f"[WHATSAPP DISPATCH SIMULATION | Recipient: {recipient}]\n"
            f"{divider}\n"
            f"{message}\n"
            f"{divider}\n"
        )
        try:
            print(output)
        except UnicodeEncodeError:
            try:
                sys.stdout.buffer.write(output.encode("utf-8", errors="replace"))
                sys.stdout.buffer.write(b"\n")
                sys.stdout.buffer.flush()
            except Exception:
                safe_output = output.encode("ascii", errors="replace").decode("ascii")
                print(safe_output)

        logger.info("Simulated dispatch to %s successfully executed.", recipient)
        return True

    def _dispatch_webhook(self, message: str, recipient: str) -> bool:
        """
        Sends message to a local or remote microservice webhook
        (e.g., Baileys / whatsapp-web.js bridge).
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.webhook_token:
            headers["Authorization"] = f"Bearer {self.webhook_token}"

        # Standard payload structure supporting common whatsapp-web microservices
        payload: Dict[str, Any] = {
            "recipient": recipient,
            "to": recipient,
            "phone": recipient,
            "chatId": f"{recipient.replace('+', '')}@c.us" if not recipient.endswith("@c.us") else recipient,
            "message": message,
            "text": message,
            "session": "default",
        }

        try:
            logger.info("Dispatching WhatsApp webhook to %s...", self.webhook_url)
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )

            if response.status_code in (200, 201, 202):
                logger.info("Webhook successfully dispatched (HTTP %d).", response.status_code)
                return True
            else:
                logger.error(
                    "Webhook failed with status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Exception during WhatsApp webhook dispatch: %s", exc)
            return False

    def _dispatch_callmebot(self, message: str, recipient: str) -> bool:
        """
        Sends message via CallMeBot's free WhatsApp gateway API.
        No business account or Meta approval needed.
        """
        if not self.callmebot_api_key:
            logger.error("CallMeBot dispatch requires CALLMEBOT_API_KEY in environment.")
            return False

        clean_recipient = recipient.replace("+", "").replace(" ", "").replace("-", "")
        url = "https://api.callmebot.com/whatsapp.php"
        params = {
            "phone": clean_recipient,
            "text": message,
            "apikey": self.callmebot_api_key,
        }

        try:
            logger.info("Dispatching WhatsApp message via CallMeBot to %s...", clean_recipient)
            response = requests.get(url, params=params, timeout=self.timeout_seconds)

            if response.status_code == 200 and "error" not in response.text.lower():
                logger.info("CallMeBot message successfully delivered.")
                return True
            else:
                logger.error(
                    "CallMeBot API failed with status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Exception during CallMeBot dispatch: %s", exc)
            return False

    def _dispatch_cloud_api(self, message: str, recipient: str) -> bool:
        """
        Sends message via WhatsApp Cloud API (Official Meta Graph API).
        """
        if not self.phone_number_id or not self.cloud_access_token:
            logger.error(
                "WhatsApp Cloud API requires WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN."
            )
            return False

        clean_recipient = recipient.replace("+", "").replace(" ", "").replace("-", "")
        url = f"{self.cloud_api_url.rstrip('/')}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.cloud_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message,
            },
        }

        try:
            logger.info("Dispatching message via WhatsApp Cloud API to %s...", clean_recipient)
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )

            if response.status_code in (200, 201):
                logger.info("WhatsApp Cloud API message delivered (HTTP %d).", response.status_code)
                return True
            else:
                logger.error(
                    "WhatsApp Cloud API failed with status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Exception during WhatsApp Cloud API dispatch: %s", exc)
            return False

    def _dispatch_telegram(self, message: str, recipient: str) -> bool:
        """
        Sends message via Telegram Bot API (100% free, instant, no phone queue).
        """
        if not self.telegram_bot_token:
            logger.error("Telegram dispatch requires TELEGRAM_BOT_TOKEN in environment.")
            return False

        target_chat = self.telegram_chat_id or recipient
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": message,
        }

        try:
            logger.info("Dispatching memo via Telegram Bot API to %s...", target_chat)
            response = requests.post(url, json=payload, timeout=self.timeout_seconds)
            if response.status_code == 200:
                logger.info("Telegram message delivered successfully.")
                return True
            else:
                logger.error(
                    "Telegram failed with status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Exception during Telegram dispatch: %s", exc)
            return False

    def _dispatch_discord(self, message: str) -> bool:
        """
        Sends message via Discord Incoming Webhook (100% free, instant, no card).
        """
        if not self.discord_webhook_url:
            logger.error("Discord dispatch requires DISCORD_WEBHOOK_URL in environment.")
            return False

        payload = {"content": message}
        try:
            logger.info("Dispatching memo via Discord Webhook...")
            response = requests.post(
                self.discord_webhook_url, json=payload, timeout=self.timeout_seconds
            )
            if response.status_code in (200, 204):
                logger.info("Discord message delivered successfully.")
                return True
            else:
                logger.error(
                    "Discord webhook failed with status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Exception during Discord dispatch: %s", exc)
            return False


# Singleton convenience instance
default_dispatcher = WhatsAppDispatcher()


def dispatch_analytics_memo(message: str, recipient: Optional[str] = None) -> bool:
    """Convenience function to dispatch using the default configured dispatcher."""
    return default_dispatcher.send_message(message, recipient)
