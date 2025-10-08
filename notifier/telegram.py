from __future__ import annotations
import requests

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self.chat_id = chat_id

    def send(self, text: str, disable_web_page_preview: bool = True) -> None:
        url = f"{self.base}/sendMessage"
        try:
            requests.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_web_page_preview,
            }, timeout=10)
        except Exception:
            pass
