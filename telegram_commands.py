from __future__ import annotations
import requests
from typing import Any, Dict, List, Tuple


class TelegramCommandPoller:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self.chat_id = str(chat_id)
        self.offset: int | None = None

    def _fetch(self, timeout: int = 25) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"timeout": timeout}
        if self.offset is not None:
            params["offset"] = self.offset
        try:
            r = requests.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 5)
            data = r.json()
            updates = data.get("result", [])
            if updates:
                self.offset = updates[-1]["update_id"] + 1
            return updates
        except Exception:
            return []

    def get_commands(self) -> List[Tuple[str, str]]:
        cmds: List[Tuple[str, str]] = []
        for u in self._fetch():
            msg = u.get("message") or u.get("edited_message") or {}
            from_id = str((msg.get("from") or {}).get("id", ""))
            if str(msg.get("chat", {}).get("id")) != self.chat_id:
                continue
            text = (msg.get("text") or "").strip().lower()
            if text.startswith("/mode ") or text in ("/pause", "/resume", "/status", "/flat", "/autocoins", "/symbols", "/risk") or text.startswith("/size ") or text.startswith("/lev "):
                cmds.append((text, from_id))
        return cmds
