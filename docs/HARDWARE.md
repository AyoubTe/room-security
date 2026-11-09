# Hardware

Everything below was bought as consumer parts. Prices are approximate (EUR, late 2026) and will
change; they are here to give a sense of scale. Total for the essentials: **roughly 215 EUR**.

## Essentials

| Part | Qty | Approx. price | Why |
|---|---|---|---|
| Raspberry Pi 4 Model B, 2 GB | 1 | 82 | Runs Sentinel, Zigbee2MQTT, go2rtc, recording and the VPN |
| USB-C power supply 5 V / 3 A | 1 | – | For the Pi |
| microSD card, high endurance, 32 GB | 1 | 28 | Built for continuous writing; the Pi runs 24/7 |
| Reolink E1 Pro 3K (5 MP) pan/tilt camera | 1 | 51 | RTSP/ONVIF, IR night vision, local HTTP API for pan/tilt. No optical zoom and no SD card in the version used here |
| Sonoff ZBDongle-E (Zigbee USB coordinator) | 1 | 19 | Talks to the Zigbee devices |
| USB 3.0 extension cable (2 m) | 1 | 11 | Keeps the dongle away from the Pi's USB 3 ports |
| Sonoff SNZB-04P contact sensor | 2 | 10 each | One for the door, one for the window |
| Sonoff SNZB-03P motion sensor | 1 | 11 | Pointed at the door area |

## Optional

| Part | Approx. price | Notes |
|---|---|---|
| Sonoff SNZB-09P Zigbee siren (105 dB) | 25 | Deters the intruder and wakes you up. Supported by Zigbee2MQTT |
| ESP32-CAM (AI-Thinker) + MQ-2 smoke module | ~10 | The separate smoke detector, see `firmware/` |
| Wi-Fi repeater or mesh node | 25–45 | Only if the camera's signal is weaker than about -70 dBm |
| Zigbee smart plug | ~10 | Acts as a Zigbee router if sensors drop out through walls |
| Second Pi as a dedicated VPN gateway | 40–60 | Redundancy; one Pi can do both jobs |
| 12 V mini UPS | ~60 | Only keeps the router alive; the Pi and camera need a 12 V to 5 V converter |

## Placement tips

- **Camera:** must see the door and the computer or valuables at the same time.
- **Motion sensor:** aim it at the door area.
- **Raspberry Pi:** next to the router on Ethernet, ideally in another room, so that someone
  inside the monitored room cannot take the recorder.
- **Zigbee dongle:** on the extension cable, away from USB 3 ports. They radiate 2.4 GHz noise and
  make the Zigbee network unstable.
- **Camera Wi-Fi:** prefer 2.4 GHz, it passes walls better than 5 GHz.
- **Compatibility:** before buying other sensors or sirens, check Zigbee 3.0 support on
  <https://www.zigbee2mqtt.io/supported-devices/>.
- **Outages:** without power or internet there is no push alert. Ping a service such as
  healthchecks.io every minute so that *you* get a message when the pings stop.
- **Privacy:** only film your own room. Check building rules and get the consent of housemates.
