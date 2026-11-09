import pytest

from sentinel.engine import (
    ALARM, ARMED, DISARMED, ENTRY_DELAY, EXIT_DELAY, Engine, SensorCfg, Timing,
)

T0 = 1_000_000.0


def make(**timing):
    sensors = [
        SensorCfg("door", "door_contact", "contact", "Door", entry_delay=True),
        SensorCfg("window", "window_contact", "contact", "Window"),
        SensorCfg("motion", "motion", "motion", "Motion", entry_delay=True),
    ]
    t = Timing(exit_delay_s=10, entry_delay_s=5, post_roll_s=100, max_event_s=1000,
               siren_s=30, baseline_s=0, **timing)
    return Engine(sensors, t, T0)


def kinds(fx, k):
    return [f for f in fx if f[0] == k]


def armed_engine(**timing):
    e = make(**timing)
    assert e.arm(T0)["ok"]
    e.tick(T0 + 10)
    assert e.state == ARMED
    e.drain()
    return e


def test_arm_goes_through_exit_delay():
    e = make()
    assert e.arm(T0) == {"ok": True, "state": EXIT_DELAY}
    assert ("camera", True) in e.drain()
    e.tick(T0 + 9)
    assert e.state == EXIT_DELAY
    e.tick(T0 + 10)
    assert e.state == ARMED


def test_sensors_ignored_during_exit_delay():
    e = make()
    e.arm(T0)
    e.drain()
    e.sensor_message("door", {"contact": False}, T0 + 3)
    assert e.state == EXIT_DELAY
    assert not kinds(e.drain(), "rec_start")


def test_arm_refused_when_window_open_unless_forced():
    e = make()
    e.sensor_message("window", {"contact": False}, T0)
    res = e.arm(T0 + 1)
    assert res == {"ok": False, "error": "open_sensors", "open": ["Window"]}
    assert e.state == DISARMED
    assert e.arm(T0 + 1, force=True)["ok"]


def test_door_opens_entry_delay_then_alarm():
    e = armed_engine()
    e.sensor_message("door", {"contact": False}, T0 + 20)
    fx = e.drain()
    assert e.state == ENTRY_DELAY
    assert kinds(fx, "rec_start")
    assert not kinds(fx, "siren")
    assert any(f[1] == "warn" and f[2] == "Entry detected" for f in kinds(fx, "notify"))
    e.tick(T0 + 24)
    assert e.state == ENTRY_DELAY
    e.tick(T0 + 25)
    fx = e.drain()
    assert e.state == ALARM
    assert ("siren", True) in fx
    assert kinds(fx, "rec_alarm")
    assert any(f[1] == "alarm" for f in kinds(fx, "notify"))


def test_disarm_during_entry_delay_cancels_everything():
    e = armed_engine()
    e.sensor_message("door", {"contact": False}, T0 + 20)
    e.drain()
    assert e.disarm(T0 + 22)["ok"]
    fx = e.drain()
    assert e.state == DISARMED
    assert kinds(fx, "rec_cancel")
    assert not kinds(fx, "rec_stop")
    assert ("siren", True) not in fx
    e.tick(T0 + 40)
    assert not kinds(e.drain(), "siren")


def test_window_is_immediate_alarm():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    fx = e.drain()
    assert e.state == ALARM
    assert ("siren", True) in fx
    assert kinds(fx, "rec_start") and kinds(fx, "rec_alarm")


def test_window_during_entry_delay_escalates_immediately():
    e = armed_engine()
    e.sensor_message("door", {"contact": False}, T0 + 20)
    e.sensor_message("window", {"contact": False}, T0 + 21)
    assert e.state == ALARM


def test_repeated_open_reports_do_not_retrigger():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    e.drain()
    e.sensor_message("window", {"contact": False, "battery": 90}, T0 + 21)
    assert not kinds(e.drain(), "rec_start")


def test_recording_continues_while_activity_and_stops_after_post_roll():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    e.drain()
    # activity keeps arriving, so the 100 s idle window keeps resetting
    for i in range(1, 6):
        e.sensor_message("motion", {"occupancy": True}, T0 + 20 + i * 60)
        e.tick(T0 + 20 + i * 60 + 1)
        assert e.state == ALARM
    last = T0 + 20 + 5 * 60
    e.drain()
    e.tick(last + 99)
    assert e.state == ALARM
    e.tick(last + 100)
    fx = e.drain()
    assert e.state == ARMED
    stops = kinds(fx, "rec_stop")
    assert len(stops) == 1 and stops[0][2] == "ended" and stops[0][3] is False


def test_siren_stops_after_its_duration_but_alarm_continues():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    e.drain()
    e.tick(T0 + 49)
    assert ("siren", False) not in e.drain()
    e.tick(T0 + 50)
    assert ("siren", False) in e.drain()
    assert e.state == ALARM


def test_max_event_length_closes_event():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    e.drain()
    t = T0 + 20
    while t < T0 + 20 + 1000:
        t += 50
        e.sensor_message("motion", {"occupancy": True}, t)
        e.tick(t)
    fx = e.drain()
    stops = kinds(fx, "rec_stop")
    assert stops and stops[0][2] == "max_length"
    assert e.state == ARMED


def test_disarm_in_alarm_stops_siren_and_uploads_rest():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    e.drain()
    e.disarm(T0 + 30)
    fx = e.drain()
    assert ("siren", False) in fx
    stop = kinds(fx, "rec_stop")[0]
    assert stop[2] == "disarmed" and stop[3] is True
    assert e.state == DISARMED


def test_motion_in_armed_room_starts_entry_delay():
    e = armed_engine()
    e.sensor_message("motion", {"occupancy": True}, T0 + 20)
    assert e.state == ENTRY_DELAY


def test_motion_clear_message_is_not_a_trigger():
    e = armed_engine()
    e.sensor_message("motion", {"occupancy": False}, T0 + 20)
    assert e.state == ARMED


def test_tamper_while_armed_is_immediate_alarm():
    e = armed_engine()
    e.sensor_message("door", {"contact": True, "tamper": True}, T0 + 20)
    assert e.state == ALARM


def test_tamper_while_disarmed_notifies_once_per_cooldown():
    e = make()
    e.sensor_message("door", {"tamper": True}, T0 + 1)
    assert len([f for f in e.drain() if f[0] == "notify"]) == 1
    e.sensor_message("door", {"tamper": False}, T0 + 2)
    e.sensor_message("door", {"tamper": True}, T0 + 3)
    assert not [f for f in e.drain() if f[0] == "notify"]


def test_low_battery_notified_once_a_day():
    e = make()
    e.sensor_message("door", {"battery": 15}, T0 + 1)
    assert len([f for f in e.drain() if f[0] == "notify"]) == 1
    e.sensor_message("door", {"battery": 14}, T0 + 100)
    assert not [f for f in e.drain() if f[0] == "notify"]
    e.sensor_message("door", {"battery": 14}, T0 + 90_000)
    assert len([f for f in e.drain() if f[0] == "notify"]) == 1


def test_baseline_window_ignores_initial_retained_messages():
    sensors = [SensorCfg("window", "w", "contact", "Window")]
    e = Engine(sensors, Timing(baseline_s=5, exit_delay_s=0), T0)
    e.restore(True, T0)
    e.drain()
    e.sensor_message("window", {"contact": False}, T0 + 1)     # retained state at startup
    assert e.state == ARMED
    assert e.sensors["window"].state == "open"
    e.sensor_message("window", {"contact": True}, T0 + 10)
    e.sensor_message("window", {"contact": False}, T0 + 11)
    assert e.state == ALARM


def test_restore_armed_after_restart():
    e = make()
    e.restore(True, T0)
    assert e.state == ARMED
    assert ("camera", True) in e.drain()
    assert e.export_state() == {"armed": True}


def test_sensor_offline_while_armed_notifies():
    e = armed_engine()
    e.availability("door", True, T0 + 20)
    e.availability("door", False, T0 + 30)
    fx = e.drain()
    assert any(f[2] == "Sensor offline" for f in kinds(fx, "notify"))


def test_camera_down_notifies_after_grace_once():
    e = armed_engine()
    e.camera(False, T0 + 20)
    e.tick(T0 + 40)
    assert not kinds(e.drain(), "notify")
    e.tick(T0 + 51)
    assert any(f[2] == "Camera offline" for f in kinds(e.drain(), "notify"))
    e.tick(T0 + 80)
    assert not kinds(e.drain(), "notify")
    e.camera(True, T0 + 90)
    assert any(f[2] == "Camera back online" for f in kinds(e.drain(), "notify"))


def test_cannot_arm_twice():
    e = make()
    e.arm(T0)
    assert e.arm(T0 + 1)["error"] == "not_disarmed"


def test_snapshot_reports_countdown():
    e = make()
    e.arm(T0)
    snap = e.snapshot(T0 + 4)
    assert snap["state"] == EXIT_DELAY and snap["remaining_s"] == 6
    names = [s["name"] for s in snap["sensors"]]
    assert names == ["door", "window", "motion"]


# ---------------------------------------------------------------- silent alarm, silencing, bypass
def test_silent_alarm_records_and_notifies_but_never_sounds_the_siren():
    e = armed_engine()
    e.silent = True
    e.sensor_message("window", {"contact": False}, T0 + 20)
    fx = e.drain()
    assert e.state == ALARM and e.alarm_silent
    assert ("siren", True) not in fx and e.siren_until is None
    assert kinds(fx, "rec_alarm")
    assert any(f[1] == "alarm" and "silent" in f[2].lower() for f in kinds(fx, "notify"))
    assert e.snapshot(T0 + 21)["alarm_silent"] is True and e.snapshot(T0 + 21)["siren_active"] is False
    e.tick(T0 + 100)                                  # siren timer must not emit a stray "off"
    assert ("siren", False) not in e.drain()


def test_silence_siren_keeps_alarm_and_recording():
    e = armed_engine()
    e.sensor_message("window", {"contact": False}, T0 + 20)
    e.drain()
    assert e.snapshot(T0 + 21)["siren_active"]
    assert e.silence_siren(T0 + 22)["ok"]
    fx = e.drain()
    assert ("siren", False) in fx and any(f[1] == "siren_silenced" for f in kinds(fx, "log"))
    assert e.state == ALARM and e.event is not None and not e.snapshot(T0 + 23)["siren_active"]
    assert e.silence_siren(T0 + 23) == {"ok": False, "error": "siren_not_sounding"}
    e.sensor_message("motion", {"occupancy": True}, T0 + 30)       # more activity does not restart it
    assert ("siren", True) not in e.drain()


def test_bypassed_window_does_not_trigger_but_door_still_does():
    e = armed_engine()
    assert e.set_bypass("window", True)
    e.sensor_message("window", {"contact": False}, T0 + 20)
    assert e.state == ARMED and not e.drain()
    e.sensor_message("door", {"contact": False}, T0 + 25)
    assert e.state == ENTRY_DELAY


def test_bypassed_door_does_not_trigger_but_window_still_does():
    e = armed_engine()
    e.set_bypass("door", True)
    e.sensor_message("door", {"contact": False}, T0 + 20)
    assert e.state == ARMED
    e.sensor_message("window", {"contact": False}, T0 + 21)
    assert e.state == ALARM


def test_open_bypassed_window_does_not_block_arming():
    e = make()
    e.sensor_message("window", {"contact": False}, T0)
    assert e.arm(T0)["error"] == "open_sensors"
    e.set_bypass("window", True)
    assert e.arm(T0)["ok"]
    assert any("sensors off: Window" in f[2] for f in kinds(e.drain(), "log"))


def test_tamper_still_alarms_on_a_bypassed_sensor():
    e = armed_engine()
    e.set_bypass("window", True)
    e.sensor_message("window", {"tamper": True}, T0 + 20)
    assert e.state == ALARM


def test_room_busy_uses_recent_motion_only():
    e = make()
    assert e.room_busy(T0, 300) == []
    e.sensor_message("motion", {"occupancy": True}, T0)
    assert e.room_busy(T0 + 299, 300) == ["Motion"]
    assert e.room_busy(T0 + 300, 300) == []
    e.sensor_message("motion", {"occupancy": True}, T0 + 400)
    e.set_bypass("motion", True)
    assert e.room_busy(T0 + 401, 300) == []


def test_armed_by_is_reported_and_restored():
    e = make()
    assert e.arm(T0, by="schedule")["ok"]
    assert e.snapshot(T0)["armed_by"] == "schedule"
    e.disarm(T0 + 1)
    assert e.snapshot(T0 + 1)["armed_by"] is None
    e2 = make()
    e2.restore(True, T0, "schedule")
    assert e2.armed_by == "schedule"
