"""Expo push notifications (https://docs.expo.dev/push-notifications/sending-notifications/)."""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("sentinel.notify")
EXPO_URL = "https://exp.host/--/api/v2/push/send"

# Channels are created by the app (src/pushNotifications.js). "intrusion" is the loud one.
CHANNEL = {"alarm": "intrusion", "warn": "intrusion", "info": "default"}


def valid_token(token: str) -> bool:
    return isinstance(token, str) and token.startswith(("ExponentPushToken[", "ExpoPushToken[")) and token.endswith("]")


class Notifier:
    def __init__(self, store, enabled: bool = True, url: str = EXPO_URL):
        self.store = store
        self.enabled = enabled
        self.url = url
        self.sent: list[dict] = []          # recent messages, handy for tests and debugging
        self.last_error: str | None = None  # why the last send delivered nothing (shown by /api/test-push)

    def build(self, token: str, level: str, title: str, body: str) -> dict:
        msg = {
            "to": token,
            "title": title,
            "body": body,
            "sound": "default",
            "priority": "high",
            "channelId": CHANNEL.get(level, "default"),
            "data": {"level": level},
            "ttl": 3600,
        }
        return msg

    async def send(self, level: str, title: str, body: str) -> int:
        tokens = self.store.tokens()
        self.last_error = None
        if not self.enabled or not tokens:
            self.last_error = "push_disabled" if not self.enabled else "no_devices"
            return 0
        messages = [self.build(t, level, title, body) for t in tokens]
        self.sent.extend(messages)
        del self.sent[:-50]
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
                async with http.post(self.url, json=messages, headers={"Accept": "application/json"}) as resp:
                    payload = await resp.json(content_type=None)
        except Exception as exc:  # network down, DNS, timeout...
            log.warning("push failed: %s", exc)
            self.last_error = "pi_offline"          # the Pi itself cannot reach Expo's servers
            return 0
        tickets = payload.get("data", []) if isinstance(payload, dict) else []
        delivered = 0
        for tok, ticket in zip(tokens, tickets):
            if ticket.get("status") == "ok":
                delivered += 1
            elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                log.info("dropping unregistered token")
                self.store.remove_token(tok)
            else:
                log.warning("push ticket error: %s", ticket)
                self.last_error = (ticket.get("details") or {}).get("error") or ticket.get("message") or "rejected"
        if delivered == 0 and self.last_error is None:
            self.last_error = "no_devices"
        return delivered
