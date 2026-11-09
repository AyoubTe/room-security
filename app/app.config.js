// Extends app.json (Expo passes its contents in as `config`), so your own EAS projectId,
// package name and other settings in app.json stay exactly as you set them.
//
// What this adds:
//  - the app logo (assets/logo/*)
//  - android.googleServicesFile, when google-services.json sits next to this file (push alerts)
//  - permission for plain http:// traffic in the installed app. The ESP32 and the
//    Raspberry Pi are reached over http://, which a release APK blocks by default
//    (Expo Go allows it, which is why the app worked there but not once installed).

const fs = require('fs');
const path = require('path');

// Firebase file for Android push (see README, "Notifications"). Optional: without it the app still builds,
// it just cannot receive alerts while closed.
const GOOGLE_SERVICES = './google-services.json';
const hasFirebase = fs.existsSync(path.join(__dirname, GOOGLE_SERVICES));

const CLEARTEXT = ['expo-build-properties', { android: { usesCleartextTraffic: true } }];

module.exports = ({ config }) => {
  const plugins = (config.plugins ?? []).filter(
    p => (Array.isArray(p) ? p[0] : p) !== 'expo-build-properties'
  );

  return {
    ...config,
    icon: './assets/logo/icon.png',
    android: {
      ...config.android,
      ...(hasFirebase ? { googleServicesFile: GOOGLE_SERVICES } : null),
      adaptiveIcon: {
        foregroundImage: './assets/logo/adaptive-foreground.png',
        monochromeImage: './assets/logo/adaptive-monochrome.png',
        backgroundColor: '#0A0C0F',
      },
    },
    web: { ...config.web, favicon: './assets/logo/favicon.png' },
    plugins: [...plugins, CLEARTEXT],
  };
};
