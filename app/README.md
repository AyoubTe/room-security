# Room Security app (Expo SDK 58), v0.7.3

The phone app for the room security system: arm and disarm, see every sensor, read the activity timeline, watch the camera live and turn it, replay the recordings of an incident, set the schedule and vacation mode. It works against the [Raspberry Pi service](../sentinel/) and the [ESP32 smoke detector](../firmware/esp32-smoke-detector/).

| Tab | What you get |
|---|---|
| **Home** | big status card (arm / disarm / silence siren), quick actions (live camera, *Air the room*, *At home today*, siren mode), key numbers, the week's schedule, a 14-day alerts chart, smoke detector, recent activity |
| **Devices** | Pi health (CPU temperature, memory, disk, services), each sensor with signal, battery and a switch-off timer, cameras, smoke detector |
| **Activity** | **Timeline** (grouped by day, filter by alarms / arming / devices, tap an alarm for its incident page with the recordings) and **Insights** (armed time, alarms vs false alarms, alerts per day, busiest hours, triggers per sensor) |
| **Settings** | theme (System / Light / Dark), schedule and vacation mode, days at home, delays, siren, camera follow, recordings and storage, tests, data source (Demo / your Pi), about |

## Run it

```bash
cd app
npm install
npx expo start          # Expo Go is enough to try the Demo mode
```

Push notifications and the installed app need a development or preview build:

```bash
npx eas-cli@latest build --profile preview --platform android
```

Use plain `npm install`. A lockfile made with `--legacy-peer-deps` is rejected by EAS (`npm ci` fails with "Missing: typescript from lock file"); `typescript` is declared in `package.json` so either kind passes, but if a build still fails there, delete `package-lock.json` and `node_modules`, run `npm install`, commit, and build again.

Before building for your own phone, edit `android.package` in `app.json` (it ships as `com.example.roomsecurity`) and link the project to your own Expo account (`npx eas-cli@latest init`).

## Configuration: `src/config.js`

The only file you edit to connect the app to your hardware:

- `SENTINEL_HOST` / `SENTINEL_TOKEN`: the Raspberry Pi's fixed LAN IP and the `api.token` from `/etc/sentinel/config.yaml`. Away from home the same address works through a Tailscale subnet route.
- `ESP32_HOST`: the smoke detector (the IP from its Serial Monitor boot log).

Until `SENTINEL_TOKEN` is changed the app runs in **Demo mode**. The file ships with placeholders: after you put your real token in it, keep it out of Git (`git update-index --skip-worktree app/src/config.js`).

## Demo mode

Two weeks of invented history (3 alarms, 5 false alarms, a day at home on Wednesdays), a simulated room you can arm, trigger and disarm, a simulated smoke detector, sample recordings and a sample camera picture that pans. A blue strip says so on every tab. Demo mode never talks to the network and never registers for push. Switch any time in **Settings -> Data source**.

## Code map

`App.js` and `index.js` start the app; everything else is in `src/`:

| Folder | Role |
|---|---|
| `theme/` | colors, type, persisted theme |
| `ui/` | design system: Card, Row, Button, Segmented, toasts and dialogs |
| `charts/` | SVG bar chart, hour strip, ring, sparkline |
| `data/` | `real.js` (Pi + ESP32 client), `demo.js` (simulator), `DataProvider.js` (polling, settings, actions) |
| `screens/` | one file per screen |
| `navigation/` | tabs and stack |
| `lib/` | pure helpers (labels, formatting of events and schedule) |

Screens never call the network directly; they use `useData()`, so the real and demo clients are interchangeable.

## Features worth knowing

- **Camera direction:** while the live view plays, a direction pad appears under the video (hold a button to keep turning, let go to stop), with a speed switch and **saved views**: point the camera, press *Save this view*, return to it with one tap (hold a view to delete it). A digital zoom (1x to 4x) sits on the picture. The screen stays awake while you watch.
- **Camera follows the intrusion:** Settings -> *Camera follows the intrusion* picks the saved view for each sensor; the Pi turns the camera there when that sensor raises an alarm, and can turn it back to a chosen view once things are quiet.
- **Recordings in the app:** Activity -> tap an alarm -> *Recordings*. Clips are streamed through the Pi from the cloud storage, so you never open Drive.
- **Recordings and storage:** keep time (default 15 days), space used, *Clean up now*. A nightly job on the Pi deletes older recordings and alerts.
- **Vacation mode** (Schedule screen): armed day and night; windows and days at home are ignored and the nightly clean-up is paused.
- Theme and data source are remembered between launches. Schedule, siren mode and sensor switches live on the Pi, so they keep working with the phone off.

## Notifications (alerts while the app is closed)

Alerts do **not** go through the app or the VPN. The Pi sends them over the internet to Expo's push service, which hands them to Google's Firebase, which wakes the phone anywhere. Tailscale is only needed to open the app's live data from outside the house.

Android needs one-time Firebase set-up (free):

1. Go to <https://console.firebase.google.com> -> **Add project** (any name, Analytics off).
2. **Add app -> Android**, with the `android.package` from `app.json`. **Download `google-services.json`** and put it next to `package.json` (it is git-ignored).
3. Project settings -> **Service accounts -> Generate new private key**. This JSON key is a secret: never share or commit it.
4. `npx eas-cli@latest credentials` -> **Android** -> the `preview` profile -> **Google Service Account -> Manage your Google Service Account Key for Push Notifications (FCM V1) -> Set up -> Upload a new key**.
5. Rebuild the APK and install it.
6. Open the app once on the home Wi-Fi (or with Tailscale on), allow notifications, and check **Settings -> Alerts on this phone** reads **On**, then press **Send a test notification**.

On some phones (Xiaomi, Oppo, Realme, Samsung) also set the app's battery use to **Unrestricted**, otherwise the system may hold alerts back while the screen is off. More: <https://docs.expo.dev/push-notifications/fcm-credentials/>

## Checks

```bash
npx expo lint
```
