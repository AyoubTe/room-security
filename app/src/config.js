/**
 * The only file you edit to connect the app to your hardware.
 *
 *  - SENTINEL_HOST / SENTINEL_TOKEN: the Raspberry Pi (its fixed LAN IP, and the api.token
 *    from /etc/sentinel/config.yaml). Away from home the same address works through the
 *    Tailscale subnet route.
 *  - ESP32_HOST: the smoke detector (the IP from its Serial Monitor boot log).
 *
 * Until SENTINEL_TOKEN is changed the app runs in Demo mode with sample data.
 */
export const SENTINEL_HOST = '192.168.1.50';
export const SENTINEL_TOKEN = 'CHANGE_ME';
export const ESP32_HOST = '192.168.1.51';

export const SENTINEL_API = `http://${SENTINEL_HOST}:8088`;
export const ESP32_API = `http://${ESP32_HOST}`;
export const SENTINEL_CONFIGURED = SENTINEL_TOKEN !== 'CHANGE_ME';
