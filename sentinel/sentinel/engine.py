"""Pure alarm state machine: no I/O and no clock of its own.

Every input takes an explicit `now` (epoch seconds) and every output is an
"effect" tuple appended to `engine.fx`; the caller drains and executes them.
That keeps all alarm logic testable with a fake clock.

States:
    disarmed -> exit_delay -> armed -> entry_delay -> alarm -> armed (again)

Effects emitted (tuples):
    ("notify", level, title, body)        level: info | warn | alarm
    ("siren", True|False)
    ("camera", True|False)                 ring-buffer capture on/off
    ("rec_start", event_id, started, why)  begin holding footage (pre-roll kept)
    ("rec_alarm", event_id)                alarm confirmed: start uploading
    ("aim", sensor_name)                   a sensor triggered: point the camera at it
    ("rec_stop", event_id, outcome, stop_camera)   finish + upload the rest
    ("rec_cancel", event_id, stop_camera)  false alarm: discard footage
    ("log", kind, text, event_id[, data])
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

DISARMED = "disarmed"
EXIT_DELAY = "exit_delay"
ARMED = "armed"
ENTRY_DELAY = "entry_delay"
ALARM = "alarm"
ACTIVE_STATES = (EXIT_DELAY, ARMED, ENTRY_DELAY, ALARM)
WATCHING_STATES = (ARMED, ENTRY_DELAY, ALARM)


@dataclass
class SensorCfg:
    name: str                 # logical name used by the app/API, e.g. "door"
    z2m: str                  # Zigbee2MQTT friendly name
    kind: str                 # "contact" | "motion"
    label: str = ""           # human text, e.g. "Door"
    entry_delay: bool = False  # True: opening starts the entry delay, not an instant alarm

    def title(self) -> str:
        return self.label or self.name


@dataclass
class Timing:
    exit_delay_s: float = 45
    entry_delay_s: float = 30
    post_roll_s: float = 600      # keep recording this long after the last activity
    max_event_s: float = 3600     # hard cap per recorded event
    siren_s: float = 120
    renotify_s: float = 60
    camera_down_s: float = 30
    tamper_cooldown_s: float = 3600
    battery_low: int = 20
    battery_cooldown_s: float = 86400
    baseline_s: float = 5         # ignore retained/initial sensor messages this long


@dataclass
class SensorState:
    cfg: SensorCfg
    state: str | None = None      # contact: open|closed   motion: motion|clear
    tamper: bool | None = None
    battery: int | None = None
    online: bool | None = None
    last_seen: float | None = None
    last_battery_alert: float = -1e12
    last_tamper_alert: float = -1e12
    bypassed: bool = False        # excluded from triggering (e.g. window open for fresh air)
    last_active: float | None = None   # last time a motion sensor reported motion
    linkquality: int | None = None     # Zigbee link quality 0-255 (as reported by the device)


class Engine:
    def __init__(self, sensors: list[SensorCfg], timing: Timing, now: float):
        self.t = timing
        self.sensors: dict[str, SensorState] = {s.name: SensorState(s) for s in sensors}
        self.state = DISARMED
        self.since = now
        self.deadline: float | None = None
        self.event: dict | None = None
        self.siren_until: float | None = None
        self.started = now
        self.camera_ok = True
        self.camera_down_since: float | None = None
        self.camera_alerted = False
        self.bridge_online: bool | None = None
        self.last_renotify = -1e12
        self.armed_by = "user"        # who armed: "user" | "schedule"
        self.silent = False           # True: alarms record and notify but the siren stays quiet
        self.alarm_silent = False     # the current alarm was raised silently
        self.fx: list[tuple] = []

    # ------------------------------------------------------------ helpers
    def drain(self) -> list[tuple]:
        out, self.fx = self.fx, []
        return out

    def _notify(self, level: str, title: str, body: str) -> None:
        self.fx.append(("notify", level, title, body))

    def _log(self, kind: str, text: str, data: dict | None = None) -> None:
        fx = ("log", kind, text, self.event["id"] if self.event else None)
        self.fx.append(fx + (data,) if data else fx)

    def _set(self, state: str, now: float, deadline: float | None = None) -> None:
        self.state = state
        self.since = now
        self.deadline = deadline

    # ------------------------------------------------------------ commands
    def open_sensors(self) -> list[str]:
        """Contact sensors that are open and not bypassed (a bypassed window is allowed to be open)."""
        return [
            s.cfg.title() for s in self.sensors.values()
            if s.cfg.kind == "contact" and s.state == "open" and not s.bypassed
        ]

    def arm(self, now: float, force: bool = False, by: str = "user") -> dict:
        if self.state != DISARMED:
            return {"ok": False, "error": "not_disarmed", "state": self.state}
        openers = self.open_sensors()
        if openers and not force:
            return {"ok": False, "error": "open_sensors", "open": openers}
        self.armed_by = by
        self._set(EXIT_DELAY, now, now + self.t.exit_delay_s)
        self.fx.append(("camera", True))
        extra = f" (bypassing open: {', '.join(openers)})" if openers else ""
        skipped = [s.cfg.title() for s in self.sensors.values() if s.bypassed]
        if skipped:
            extra += f" (sensors off: {', '.join(skipped)})"
        who = "Auto-arming by schedule" if by == "schedule" else "Arming"
        self._log("arming", f"{who}, leave within {int(self.t.exit_delay_s)} s{extra}")
        return {"ok": True, "state": self.state}

    def disarm(self, now: float, by: str = "user") -> dict:
        if self.state == DISARMED:
            return {"ok": True, "state": self.state}
        prev = self.state
        if prev == ALARM or self.siren_until is not None:
            self.fx.append(("siren", False))
            self.siren_until = None
        self.alarm_silent = False
        if self.event:
            self._close_event("disarmed", stop_camera=True)
        else:
            self.fx.append(("camera", False))
        self._set(DISARMED, now)
        note = {
            ENTRY_DELAY: "Disarmed during entry delay (no alarm)",
            ALARM: "Disarmed while alarm was active",
        }.get(prev, "System disarmed")
        if by == "schedule":
            note = "Schedule window ended, system disarmed"
        self._log("disarmed", note)
        return {"ok": True, "state": self.state}

    def silence_siren(self, now: float) -> dict:
        """Stop the siren but keep the alarm, recording and uploads running."""
        if self.siren_until is None:
            return {"ok": False, "error": "siren_not_sounding"}
        self.siren_until = None
        self.fx.append(("siren", False))
        self._log("siren_silenced", "Siren silenced from the app (recording continues)")
        return {"ok": True, "state": self.state}

    def set_bypass(self, name: str, bypassed: bool) -> bool:
        """Mark a sensor as ignored/active. Returns True if it changed."""
        s = self.sensors.get(name)
        if s is None or s.bypassed == bypassed:
            return False
        s.bypassed = bypassed
        return True

    def room_busy(self, now: float, busy_s: float) -> list[str]:
        """Names of motion sensors that saw movement in the last `busy_s` seconds."""
        return [
            s.cfg.title() for s in self.sensors.values()
            if s.cfg.kind == "motion" and not s.bypassed and s.last_active is not None
            and now - s.last_active < busy_s
        ]

    def restore(self, armed: bool, now: float, by: str = "user") -> None:
        """Called once at startup with the persisted armed flag."""
        if armed:
            self.armed_by = by
            self._set(ARMED, now)
            self.fx.append(("camera", True))
            self._log("restored", "Service restarted: system is armed")

    def export_state(self) -> dict:
        return {"armed": self.state in ACTIVE_STATES}

    # ------------------------------------------------------------ inputs
    def sensor_message(self, name: str, values: dict, now: float) -> None:
        s = self.sensors.get(name)
        if s is None:
            return
        s.last_seen = now
        baseline = (now - self.started) < self.t.baseline_s

        lq = values.get("linkquality")
        if isinstance(lq, (int, float)) and not isinstance(lq, bool):
            s.linkquality = int(lq)

        bat = values.get("battery")
        if isinstance(bat, (int, float)) and not isinstance(bat, bool):
            s.battery = int(bat)
            self._check_battery(s, now)

        if "tamper" in values:
            self._on_tamper(s, bool(values["tamper"]), now, baseline)

        if s.cfg.kind == "contact" and "contact" in values:
            prev = s.state
            s.state = "closed" if values["contact"] else "open"
            if s.state == "open" and prev != "open" and not baseline and not s.bypassed:
                self._trigger(s, f"{s.cfg.title()} opened", now, immediate=not s.cfg.entry_delay)

        if s.cfg.kind == "motion" and "occupancy" in values:
            s.state = "motion" if values["occupancy"] else "clear"
            if s.state == "motion":
                s.last_active = now
                if not baseline and not s.bypassed:
                    self._trigger(s, f"Motion: {s.cfg.title()}", now, immediate=not s.cfg.entry_delay)

    def availability(self, name: str, online: bool, now: float) -> None:
        s = self.sensors.get(name)
        if s is None or s.online == online:
            return
        was_known = s.online is not None
        s.online = online
        if not was_known and online:
            return
        if self.state in ACTIVE_STATES:
            if not online:
                self._notify("warn", "Sensor offline", f"{s.cfg.title()} stopped responding. It may be jammed or out of battery.")
            else:
                self._notify("info", "Sensor back online", f"{s.cfg.title()} is responding again.")
        self._log("sensor_offline" if not online else "sensor_online", f"{s.cfg.title()} {'offline' if not online else 'online'}")

    def bridge(self, online: bool, now: float) -> None:
        if self.bridge_online == online:
            return
        was_known = self.bridge_online is not None
        self.bridge_online = online
        if not was_known and online:
            return
        if not online:
            self._log("zigbee_down", "Zigbee2MQTT went offline")
            if self.state in ACTIVE_STATES:
                self._notify("warn", "Zigbee offline", "Sensors cannot reach the system. The room is not fully protected.")
        else:
            self._log("zigbee_up", "Zigbee2MQTT back online")

    def camera(self, ok: bool, now: float) -> None:
        if ok == self.camera_ok:
            return
        self.camera_ok = ok
        if not ok:
            self.camera_down_since = now
        else:
            if self.camera_alerted and self.state in WATCHING_STATES:
                self._notify("info", "Camera back online", "Recording resumed.")
            self.camera_down_since = None
            self.camera_alerted = False

    # ------------------------------------------------------------ internals
    def _check_battery(self, s: SensorState, now: float) -> None:
        if s.battery is not None and s.battery <= self.t.battery_low:
            if now - s.last_battery_alert > self.t.battery_cooldown_s:
                s.last_battery_alert = now
                self._notify("warn", "Low battery", f"{s.cfg.title()} is at {s.battery}%.")
                self._log("battery", f"{s.cfg.title()} battery {s.battery}%")

    def _on_tamper(self, s: SensorState, tampered: bool, now: float, baseline: bool) -> None:
        prev = s.tamper
        s.tamper = tampered
        if not tampered or prev is True or baseline:
            return
        if self.state in WATCHING_STATES:
            self._trigger(s, f"Tamper: {s.cfg.title()}", now, immediate=True)
        elif now - s.last_tamper_alert > self.t.tamper_cooldown_s:
            s.last_tamper_alert = now
            self._notify("warn", "Tamper alert", f"{s.cfg.title()} was tampered with.")
            self._log("tamper", f"Tamper: {s.cfg.title()}")

    def _open_event(self, reason: str, now: float, sensor: str | None = None) -> None:
        eid = f"{int(now)}-{uuid.uuid4().hex[:4]}"
        self.event = {"id": eid, "started": now, "reason": reason, "alarm_at": None, "last_activity": now}
        self.fx.append(("rec_start", eid, now, reason))
        self._log("trigger", reason, {"sensor": sensor} if sensor else None)

    def _trigger(self, s: SensorState, reason: str, now: float, immediate: bool) -> None:
        st = self.state
        if st in (DISARMED, EXIT_DELAY):
            return
        self.fx.append(("aim", s.cfg.name))           # let the camera turn to where it happened
        if st == ARMED:
            self._open_event(reason, now, s.cfg.name)
            if immediate:
                self._to_alarm(reason, now)
            else:
                self._set(ENTRY_DELAY, now, now + self.t.entry_delay_s)
                self._notify(
                    "warn", "Entry detected",
                    f"{reason}. Disarm within {int(self.t.entry_delay_s)} s or the alarm sounds.",
                )
        elif st == ENTRY_DELAY:
            self.event["last_activity"] = now
            if immediate:
                self._to_alarm(reason, now)
        elif st == ALARM:
            self.event["last_activity"] = now
            if now - self.last_renotify >= self.t.renotify_s:
                self.last_renotify = now
                self._notify("alarm", "Intrusion still active", reason)

    def _to_alarm(self, reason: str, now: float) -> None:
        self._set(ALARM, now)
        self.event["alarm_at"] = now
        self.event["last_activity"] = now
        self.last_renotify = now
        self.alarm_silent = self.silent
        if self.silent:
            self.siren_until = None
            note = " (silent: siren muted)"
        else:
            self.siren_until = now + self.t.siren_s
            self.fx.append(("siren", True))
            note = ""
        self.fx.append(("rec_alarm", self.event["id"]))
        body = f"{reason}. Silent mode: the siren is off, recording is on." if self.silent else reason
        self._notify("alarm", "INTRUSION ALARM" + (" (silent)" if self.silent else ""), body)
        self._log("alarm", f"ALARM: {reason}{note}")

    def _close_event(self, outcome: str, stop_camera: bool) -> None:
        ev = self.event
        self.event = None
        if ev is None:
            return
        if ev["alarm_at"] is not None:
            self.fx.append(("rec_stop", ev["id"], outcome, stop_camera))
        else:
            self.fx.append(("rec_cancel", ev["id"], stop_camera))

    # ------------------------------------------------------------ clock
    def tick(self, now: float) -> None:
        if self.state == EXIT_DELAY and self.deadline is not None and now >= self.deadline:
            self._set(ARMED, now)
            self._log("armed", "System armed")
            self._notify("info", "Armed", "The room is now being watched.")

        elif self.state == ENTRY_DELAY and self.deadline is not None and now >= self.deadline:
            self._to_alarm(f"Entry delay expired ({self.event['reason']})", now)

        if self.state == ALARM and self.event is not None:
            if self.siren_until is not None and now >= self.siren_until:
                self.fx.append(("siren", False))
                self.siren_until = None
            ev = self.event
            idle = now - ev["last_activity"] >= self.t.post_roll_s
            too_long = now - ev["started"] >= self.t.max_event_s
            if idle or too_long:
                outcome = "ended" if idle else "max_length"
                self._log("alarm_end", "Activity ended, recording closed" if idle else "Maximum recording length reached")
                self._close_event(outcome, stop_camera=False)
                self._set(ARMED, now)

        if (
            self.state in WATCHING_STATES
            and not self.camera_ok
            and self.camera_down_since is not None
            and not self.camera_alerted
            and now - self.camera_down_since >= self.t.camera_down_s
        ):
            self.camera_alerted = True
            self._notify("warn", "Camera offline", "The camera stopped sending video. Recording is unavailable.")
            self._log("camera_down", "Camera offline")

    # ------------------------------------------------------------ view
    def snapshot(self, now: float) -> dict:
        remaining = None
        if self.deadline is not None and self.state in (EXIT_DELAY, ENTRY_DELAY):
            remaining = max(0, int(round(self.deadline - now)))
        return {
            "state": self.state,
            "since": self.since,
            "remaining_s": remaining,
            "armed": self.state in ACTIVE_STATES,
            "siren_active": self.siren_until is not None,
            "siren_silent": self.silent,
            "alarm_silent": self.alarm_silent and self.state == ALARM,
            "armed_by": self.armed_by if self.state in ACTIVE_STATES else None,
            "camera_ok": self.camera_ok,
            "zigbee_ok": self.bridge_online is not False,
            "event": (
                {"id": self.event["id"], "reason": self.event["reason"], "started": self.event["started"]}
                if self.event else None
            ),
            "sensors": [
                {
                    "name": s.cfg.name,
                    "label": s.cfg.title(),
                    "kind": s.cfg.kind,
                    "state": s.state or "unknown",
                    "tamper": bool(s.tamper),
                    "battery": s.battery,
                    "online": s.online,
                    "last_seen": s.last_seen,
                    "linkquality": s.linkquality,
                    "bypassed": s.bypassed,
                }
                for s in self.sensors.values()
            ],
        }
