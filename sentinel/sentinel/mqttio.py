"""Zigbee2MQTT bridge: turns MQTT messages into engine inputs and sends siren commands."""

from __future__ import annotations

import json
import logging

log = logging.getLogger("sentinel.mqtt")


def parse_message(base: str, by_z2m: dict[str, str], topic: str, payload: bytes):
    """Pure parser, separate from paho so it can be unit-tested.

    Returns one of:
        ("values", logical_name, dict)
        ("avail", logical_name, bool)
        ("bridge", bool)
        None
    """
    text = payload.decode("utf-8", errors="replace").strip()

    def parse_state(t: str):
        if not t:
            return None
        try:
            data = json.loads(t)
        except ValueError:
            data = t
        if isinstance(data, dict):
            data = data.get("state")
        if isinstance(data, str) and data.lower() in ("online", "offline"):
            return data.lower() == "online"
        return None

    if topic == f"{base}/bridge/state":
        online = parse_state(text)
        return None if online is None else ("bridge", online)

    if not topic.startswith(base + "/"):
        return None
    rest = topic[len(base) + 1:]

    if rest.endswith("/availability"):
        name = by_z2m.get(rest[: -len("/availability")])
        online = parse_state(text)
        if name is None or online is None:
            return None
        return ("avail", name, online)

    name = by_z2m.get(rest)
    if name is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return ("values", name, data) if isinstance(data, dict) else None


WARNING_LEVEL = {"low": "low", "medium": "medium", "high": "high", "max": "very_high"}


def siren_payloads(siren: dict, on: bool, duration: float | None = None, volume: str | None = None) -> list[dict]:
    dur = int(duration if duration is not None else siren["duration_s"])
    if siren["type"] == "warning":
        if on:
            level = WARNING_LEVEL.get(volume or "max", "very_high")
            return [{"warning": {"mode": "burglar", "level": level, "strobe": True, "duration": dur}}]
        return [{"warning": {"mode": "stop", "level": "low", "strobe": False, "duration": 0}}]
    if on:
        # The SNZB-09P sounds "siren_on" with whatever it is configured to use, and the sound and light
        # switches can be OFF (a factory state, or switched off by hand): then nothing is heard. So switch them on every time.
        # Zigbee2MQTT reads these two as "ON"/"OFF" text: a true/false value ends up OFF, so convert it.
        settings = {"alarm_sound_enable": "ON", "alarm_light_enable": "ON", **siren.get("settings", {})}
        for key in ("alarm_sound_enable", "alarm_light_enable"):
            if isinstance(settings.get(key), bool):
                settings[key] = "ON" if settings[key] else "OFF"
        if volume:
            settings["alarm_volume_level"] = volume
        return [{**settings, "alarm_duration": dur}, {"siren_on": "ON"}]
    return [{"siren_on": "OFF"}]


class Z2M:
    def __init__(self, cfg: dict, loop, on_values, on_avail, on_bridge):
        m = cfg["mqtt"]
        self.cfg = m
        self.base = m["base_topic"].rstrip("/")
        self.loop = loop
        self.on_values, self.on_avail, self.on_bridge = on_values, on_avail, on_bridge
        self.by_z2m = {f"{s['z2m']}": s["name"] for s in cfg["sensors"]}
        self.client = None
        self.connected = False

    def start(self) -> None:
        import paho.mqtt.client as mqtt

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinel")
        if self.cfg.get("username"):
            c.username_pw_set(self.cfg["username"], self.cfg.get("password") or None)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        c.connect_async(self.cfg["host"], int(self.cfg["port"]), keepalive=30)
        c.loop_start()
        self.client = c

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = not getattr(reason_code, "is_failure", False)
        log.info("mqtt connected: %s", reason_code)
        client.subscribe([(f"{self.base}/bridge/state", 0)])
        for z in self.by_z2m:
            client.subscribe([(f"{self.base}/{z}", 0), (f"{self.base}/{z}/availability", 0)])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        log.warning("mqtt disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        parsed = parse_message(self.base, self.by_z2m, msg.topic, msg.payload)
        if parsed is None:
            return
        if parsed[0] == "values":
            self.loop.call_soon_threadsafe(self.on_values, parsed[1], parsed[2])
        elif parsed[0] == "avail":
            self.loop.call_soon_threadsafe(self.on_avail, parsed[1], parsed[2])
        else:
            self.loop.call_soon_threadsafe(self.on_bridge, parsed[1])

    def publish(self, z2m_name: str, payload: dict) -> bool:
        if not self.client or not self.connected:
            log.warning("mqtt not connected; dropped %s", payload)
            return False
        self.client.publish(f"{self.base}/{z2m_name}/set", json.dumps(payload), qos=1)
        return True
