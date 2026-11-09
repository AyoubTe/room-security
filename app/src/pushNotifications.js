/**
 * Push notification setup — call setupPushNotifications() once when the app
 * starts. It requests permission, grabs this device's Expo push token, and
 * registers it with the ESP32 (smoke alerts) and the Pi (intrusion alerts) so
 * both know where to send notifications.
 *
 * Requires a linked EAS project (run `eas init` once) so Constants can find
 * a projectId — without it, getExpoPushTokenAsync() throws.
 */

import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

// Controls how a notification behaves while the app is open and in the
// foreground. shouldShowBanner/shouldShowList replace the old
// shouldShowAlert flag as of expo-notifications' SDK 58 API.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * What happened the last time this phone tried to sign up for alerts, for the Settings screen.
 * status: unknown | ready | pi_unreachable | denied | no_firebase | error | simulator | expo_go
 */
let pushState = { status: 'unknown', detail: '' };
const setState = (status, detail = '') => { pushState = { status, detail }; };
export const getPushState = () => pushState;

export async function setupPushNotifications(client) {
  if (!Device.isDevice) {
    console.warn('Push notifications require a physical device, not a simulator/emulator');
    setState('simulator');
    return null;
  }

  // Expo Go on Android has not supported remote push since SDK 53 — even
  // setNotificationChannelAsync() throws a native NullPointerException
  // there. Environment flags (appOwnership/executionEnvironment) turned out
  // unreliable for detecting this ahead of time, so the call itself is
  // wrapped instead — this is the one call actually known to throw there.
  if (Platform.OS === 'android') {
    try {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Smoke alerts',
        // AndroidImportance is a real runtime export (re-exported from
        // NotificationChannelManager.types) — the lint resolver just can't
        // trace expo-notifications' re-export chain.
        // eslint-disable-next-line import/namespace
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#3FD6C0',
      });
      // Loud channel used by the Pi for intrusion alerts (the Pi sends channelId: 'intrusion').
      await Notifications.setNotificationChannelAsync('intrusion', {
        name: 'Intrusion alerts',
        // eslint-disable-next-line import/namespace
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 500, 250, 500, 250, 500],
        lightColor: '#3FD6C0',
        sound: 'default',
      });
    } catch {
      console.warn(
        'Skipping push notification setup: Expo Go on Android cannot register for remote ' +
        'push since SDK 53. Everything else in the app (live status, camera, snapshots) is ' +
        'unaffected. To test real push delivery, build a development client once with ' +
        '`eas build --profile development --platform android` and install that APK instead ' +
        'of using Expo Go.'
      );
      setState('expo_go');
      return null;
    }
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== 'granted') {
    console.warn('Notification permission was not granted');
    setState('denied');
    return null;
  }

  const projectId =
    Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;

  if (!projectId) {
    console.error('No EAS project ID found in app.json. Run `eas init` in the project root first.');
    setState('error', 'No EAS project ID in the app');
    return null;
  }

  let expoPushToken;
  try {
    const tokenResponse = await Notifications.getExpoPushTokenAsync({ projectId });
    expoPushToken = tokenResponse.data;
  } catch (e) {
    console.error('Failed to get Expo push token:', e);
    // Without google-services.json inside the app, Android cannot hand out a push token at all.
    setState(/firebase|fcm|google-services|google play/i.test(String(e?.message ?? e)) ? 'no_firebase' : 'error', String(e?.message ?? e).slice(0, 200));
    return null;
  }

  try {
    await client.registerSmokePush(expoPushToken);
    console.log('Registered push token with the ESP32:', expoPushToken);
  } catch (e) {
    // Most likely the phone isn't on the same WiFi as the ESP32 right now. Not fatal: retried on every launch.
    console.warn('Could not reach the ESP32 to register the push token:', e);
  }

  // Same token, second sender: the Pi security service. Also retried on every launch.
  try {
    await client.registerPush(expoPushToken);
    console.log('Registered push token with the Pi');
    setState('ready');
  } catch (e) {
    console.warn('Could not reach the Pi to register the push token:', e);
    setState('pi_unreachable');
  }

  return expoPushToken;
}
