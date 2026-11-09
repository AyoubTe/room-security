# Room security: Pi setup

What runs on the Raspberry Pi 4 (all local, all small):

| Piece | Job |
|---|---|
| Mosquitto | message bus between Zigbee2MQTT and the sentinel |
| Zigbee2MQTT | talks to the door/window/motion sensors and the siren through the USB dongle |
| **sentinel** (this project) | arm/disarm, entry/exit delay, siren, push alerts, recording, cloud upload, API for the app |
| go2rtc | on-demand live video for the app (only pulls from the camera while you watch) |
| rclone | uploads clips to Google Drive (or another cloud) |
| Tailscale | lets the phone reach the Pi from outside your home |

> The commands below follow each project's official install guide. If a step fails on your system,
> compare with the official page (linked in each step) first, versions move.

## 1. Flash the Pi

1. Raspberry Pi Imager -> **Raspberry Pi OS Lite (64-bit)**. In the settings (gear icon): hostname `sentinel`, enable SSH, set a user and password, set your locale.
2. Put the SanDisk High Endurance card in, plug **Ethernet to your router**, power on.
3. In your router's admin page, **reserve a fixed IP** for the Pi (for example `192.168.1.50`).
4. From your PC: `ssh <user>@192.168.1.50`, then:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y mosquitto mosquitto-clients ffmpeg python3-venv git curl rclone
sudo systemctl enable --now mosquitto
```

## 2. Tailscale (remote access)

Official guide: https://tailscale.com/kb/1019/subnets

```bash
curl -fsSL https://tailscale.com/install.sh | sh
echo 'net.ipv4.ip_forward = 1' | sudo tee /etc/sysctl.d/99-tailscale.conf
sudo sysctl -p /etc/sysctl.d/99-tailscale.conf
sudo tailscale up --advertise-routes=192.168.1.0/24
```

Open the printed login link, then in the Tailscale admin console approve the subnet route
(Machines -> the Pi -> Edit route settings). This also gives the phone access to the ESP32 smoke detector.

## 3. Zigbee2MQTT

Official guide: https://www.zigbee2mqtt.io/guide/installation/01_linux.html

Plug the dongle into the Pi **using the USB extension cable, in a black (USB 2.0) port**, then:

```bash
sudo apt install -y ca-certificates curl gnupg git make g++ gcc libsystemd-dev
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo corepack enable
sudo mkdir /opt/zigbee2mqtt && sudo chown -R $USER: /opt/zigbee2mqtt
git clone --depth 1 https://github.com/Koenkk/zigbee2mqtt.git /opt/zigbee2mqtt
cd /opt/zigbee2mqtt && pnpm i --frozen-lockfile
ls /dev/serial/by-id/            # copy the dongle's path
```

Copy `deploy/zigbee2mqtt-configuration.yaml` to `/opt/zigbee2mqtt/data/configuration.yaml` and put your dongle path in `serial.port`.
Install the service (edit `User=` in the file if your user is not `pi`):

```bash
sudo cp deploy/zigbee2mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now zigbee2mqtt
```

**Pair the devices.** Open `http://192.168.1.50:8081`, click **Permit join (All)**, then put each device in pairing mode
(for the Sonoff sensors and siren: hold the button about 5 seconds until the LED blinks; see each manual). Pair them **next to the dongle**, then move them to their final place.
Rename them in the web UI to match `config.yaml`: `door_contact`, `window_contact`, `motion`, `siren` (the example file shows `retain: true` for the sensors).
Turn Permit join off when done.

In the web UI, open the siren's **Exposes** tab and check it offers `siren_on` and `alarm_volume_level`. If it offers a `warning` control instead, set `siren.type: warning` in the sentinel config.

## 4. go2rtc (live view)

Download the arm64 build from https://github.com/AlexxIT/go2rtc/releases (file named like `go2rtc_linux_arm64`):

```bash
sudo install -m 755 ~/go2rtc_linux_arm64 /usr/local/bin/go2rtc
```

## 5. The sentinel service

On the Pi, from the `sentinel/` folder of this repository (clone the repository there, or copy that folder over with `scp -r`):

```bash
sudo useradd -r -m -d /var/lib/sentinel -s /usr/sbin/nologin sentinel
sudo mkdir -p /opt/sentinel /etc/sentinel
sudo cp -r sentinel requirements.txt /opt/sentinel/
sudo python3 -m venv /opt/sentinel/venv
sudo /opt/sentinel/venv/bin/pip install -r /opt/sentinel/requirements.txt

sudo cp config.example.yaml /etc/sentinel/config.yaml
sudo cp deploy/go2rtc.yaml /etc/sentinel/go2rtc.yaml
sudo chown root:sentinel /etc/sentinel/*.yaml && sudo chmod 640 /etc/sentinel/*.yaml
sudo nano /etc/sentinel/config.yaml        # token, camera URLs, cloud remote
sudo nano /etc/sentinel/go2rtc.yaml        # camera URL (sub stream)
```

Generate the token with `openssl rand -hex 24` and keep it: the app needs the same value.

### The camera (Reolink E1 Pro)

1. Set it up in the Reolink app, give it a fixed IP in your router, and set a strong password.
2. In the Reolink app's device settings, make sure **RTSP and ONVIF are enabled** (Network -> Advanced -> Server Settings, wording varies).
3. **Turn off auto-tracking and patrol** so it always looks at the door and your PC.
   (If either is on, the camera fights the app's direction pad.)
4. Test the stream on your PC with VLC (Media -> Open Network Stream) with the same URL as in `config.yaml`. If the path does not work, try `/h264Preview_01_main`.

### Turning the camera from the app

Nothing to configure: the Pi reuses the camera address, user and password from `camera.rtsp_main` and talks to the camera's own control interface (HTTP, port 80). In the app, open the camera, press **Watch live**, and a direction pad appears under the video. Hold a button to keep turning; the Pi also stops the camera by itself after a few seconds, so a lost connection can never leave it spinning.

- **Saved views:** point the camera, press **Save this view**, give it a name. They are stored in the camera (up to 64) and work with the Reolink app too.
- **Watch the door when armed:** set `camera.ptz.arm_preset` to the number of a saved view (the order you saved them in; the first one is 1) and the camera turns back to it each time the room is armed. In the app, that view is marked with a shield.
- **Test from the Pi:**
  ```bash
  curl -s -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8088/api/ptz
  ```
  `"supported": true` means the Pi can steer the camera. If the app shows no pad, check that the camera password has only letters and digits (or is URL-encoded in the RTSP URL) and that the camera is a pan-tilt model.

### Cloud storage (Google Drive via rclone)

```bash
sudo -u sentinel rclone config --config /var/lib/sentinel/rclone.conf
```

Choose `n` (new remote), name it `gdrive`, storage `drive`, accept defaults, and pick the scope **`drive.file`** (only files rclone created).
When asked "Use auto config?" answer **n**; it prints a command to run on your Windows PC (`rclone authorize "drive" "..."`). Run it there, sign in, and paste the token back.
Check it: `sudo -u sentinel rclone --config /var/lib/sentinel/rclone.conf lsd gdrive:` .

### Camera follows the intrusion, recordings in the app, nightly clean-up, vacation mode

- **Camera follows**: save three views on the Camera screen (for example Centre, Window, Door), then
  Settings, Camera follows the intrusion: pick the view for each sensor. When a sensor triggers an alarm
  the Pi turns the camera to that view (needs the camera controls above to work).
- **Return to**: in the same screen choose the view the camera goes back to (for example Centre) once the
  intrusion has been quiet for 1, 2 or 5 minutes. The quiet time starts when the alarm ends, and the camera
  is left alone if you turned it yourself in the meantime.
- **Watch recordings in the app**: Activity, tap an alarm, Recordings. Clips stream through the Pi from
  Google Drive (`rclone cat`), so Drive stays private and you never open it. Clips not uploaded yet play from the Pi.
- **Nightly clean-up** at `cloud.cleanup_at` (03:30): event folders and alerts older than the keep time
  (default 15 days, change it in Settings, Recordings and storage; "Keep all" disables it) are deleted.
  Only folders named like `2026-11-07_13-11-49_a1b2` are ever touched. Deletion skips the Drive bin.
- **Vacation mode** (Schedule screen): armed day and night, windows and days at home ignored, and
  the clean-up is paused so nothing is deleted while you are away. If you disarm by hand the room stays
  disarmed until you press "Arm again". It ends on its date or when you press the button.

### Start everything

```bash
sudo cp deploy/sentinel.service deploy/go2rtc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now go2rtc sentinel
journalctl -u sentinel -f                  # live log; Ctrl+C to leave
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8088/api/status
```

## 6. The app

In the app's `src/config.js` set `SENTINEL_HOST` (the Pi's IP) and `SENTINEL_TOKEN` (same value as `api.token` above), then rebuild the APK
(`npx eas-cli@latest build --profile preview --platform android`). Until the token is set the app runs in **Demo mode** with sample data, so you can explore it before the Pi exists.
The app has four tabs: **Home** (status, quick actions, charts), **Devices** (Pi health, sensors, cameras), **Activity** (timeline and insights) and **Settings**.

The dashboards are fed by `GET /api/insights?days=14` (alarms and triggers per day, armed time, busiest hours, triggers per sensor) and the `system` block of `GET /api/status` (CPU temperature, memory, disk, link quality of each sensor). Nothing to configure: they fill in as the Pi collects history.

## 7. Test before you trust it

Run these with the siren volume in mind (tell the neighbors, or test in the daytime):

1. App -> Home -> **Arm the room**. Leave the room within 45 s.
2. Open the door: you should get an "Entry detected" push, then 30 s later the alarm, the siren, and an "INTRUSION ALARM" push.
3. Open Google Drive: a folder `SecurityCam/<date_time_id>/` with `snapshot.jpg` and `part_001.mp4`, `part_002.mp4`, ... appears within about a minute.
4. Disarm in the app: the siren stops and the remaining footage uploads.
5. Arm again, open the door, and **disarm within 30 s**: no alarm, nothing uploaded.
6. Unplug the camera while armed: a "Camera offline" push arrives after about 30 s.
7. With the app on mobile data (Wi-Fi off, Tailscale on), check that arm/disarm and Watch live still work.
8. **Silent mode:** Settings -> Siren -> **Silent**, arm, open the window. You get an "INTRUSION ALARM (silent)" push and footage uploads, but the siren stays quiet.
9. **Silence button:** switch back to **Siren on**, trigger an alarm in the daytime and press **Silence siren** on Home: the siren stops, the alarm and recording go on.
10. **Window off:** Devices -> Window -> **For 1 hour** (or the **Air the room** shortcut on Home), arm, open the window: nothing happens. Open the door: the entry delay starts as usual.
11. **Schedule:** Settings -> Schedule -> add a window starting 3 minutes from now, with a 5 min pre-arm warning. You get the warning, then the room arms by itself. Press **Disarm** inside the window: it stays disarmed until the window ends (Settings -> Schedule -> Resume undoes that).

## Schedule, silent siren and sensors (all from the app)

These live in the app's **Settings** tab (Schedule, Days at home, Siren, Delays) and on the Devices tab (sensors) and are stored on the Pi, so they survive restarts. `config.yaml` only holds the defaults and `timezone`.

- **Windows:** each one has days of the week, an arm time and a disarm time. If the end is earlier than the start it runs overnight (22:00 to 07:00). Touching windows merge, so there is no gap.
- **Days at home:** mark single days, or a weekday you always work from home (every Wednesday). A day at home cancels the windows that start that day, even if you forget to turn anything off. Marking *today* while the schedule has armed the room disarms it.
- **Manual disarm** inside a window means "I'm in the room": the schedule won't arm again until that window is over, or you press **Resume**. A room you armed by hand is never disarmed by the schedule.
- **Smart arming:** auto-arm waits while the motion sensor saw movement in the last 2 to 15 minutes, or while a door is open, and arms as soon as the room is quiet. You are told once ("Auto-arm postponed"). A PIR cannot see someone sitting perfectly still, so keep the pre-arm warning on as a safety net.
- **Siren modes:** *On*, *Silent* (records, uploads and notifies, never sounds) or *Quiet hours* (silent between two times, loud otherwise). Volume and duration are adjustable. **Silence siren** in the app stops it remotely during an alarm.
- **Sensors:** each sensor can be switched off for 1/2/4 hours, until a window is closed again, or until you turn it back on. A sensor on a timer turns itself back on and warns you if the window is still open then. Tamper alerts stay active on a switched-off sensor. An open window that is switched off does not stop you arming.
- **Limits:** the system cannot sense a window that is already open when its protection comes back on. A cut Zigbee link or a dead Pi bypasses all of this, which is why the healthchecks.io ping is worth setting up.

## Good to know

- **No recording while disarmed.** The camera is only read while the system is armed.
- **Footage timing.** The 30 s before the first trigger is kept (RAM only), and clips upload in 60 s parts, so a thief who takes the Pi loses at most the last minute.
- **10-minute rule.** Recording continues while there is activity and stops 10 minutes after the last detection (`post_roll_s`). Change it in `config.yaml`.
- **Drive storage.** About 150 to 300 MB per 10 minutes of video. Free Drive space is 15 GB, shared with Gmail and Photos.
- **Deleting evidence.** Anyone who steals the Pi also gets the rclone token. For tamper-proof storage use Backblaze B2 with an application key that has no delete permission (rclone remote of type `b2`); only `cloud.remote` changes.
- **Power or internet cut.** There is no battery backup. Add a healthchecks.io ping URL so you are emailed when the Pi goes silent.
