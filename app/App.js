import { useEffect } from 'react';
import { AppState } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { PaperProvider } from 'react-native-paper';
import { Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold, useFonts } from '@expo-google-fonts/inter';

import { ThemeProvider, useAppTheme } from './src/theme/ThemeProvider.js';
import { DataProvider, useData } from './src/data/DataProvider.js';
import { FeedbackProvider } from './src/ui/index.js';
import Navigation from './src/navigation/index.js';
import { setupPushNotifications } from './src/pushNotifications.js';

/** Registers this phone for push alerts, only when talking to the real Pi (never in demo mode). */
function PushSetup() {
  const { client, source } = useData();
  useEffect(() => {
    if (source !== 'live' || !client) return undefined;
    setupPushNotifications(client);
    // The phone may not have reached the Pi at launch (mobile data, VPN off): try again whenever the app is brought back.
    const sub = AppState.addEventListener('change', s => { if (s === 'active') setupPushNotifications(client); });
    return () => sub.remove();
  }, [source, client]);
  return null;
}

function Shell({ fontsLoaded }) {
  const { ready, paper, dark } = useAppTheme();
  const { ready: dataReady } = useData();
  if (!fontsLoaded || !ready || !dataReady) return null;
  return (
    <PaperProvider theme={paper}>
      <FeedbackProvider>
        <StatusBar style={dark ? 'light' : 'dark'} />
        <PushSetup />
        <Navigation />
      </FeedbackProvider>
    </PaperProvider>
  );
}

function Providers({ fontsLoaded }) {
  return (
    <ThemeProvider>
      <DataProvider>
        <Shell fontsLoaded={fontsLoaded} />
      </DataProvider>
    </ThemeProvider>
  );
}

export default function App() {
  const [fontsLoaded] = useFonts({ Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold });
  return (
    <SafeAreaProvider>
      <Providers fontsLoaded={fontsLoaded} />
    </SafeAreaProvider>
  );
}
