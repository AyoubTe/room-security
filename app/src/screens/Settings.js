import { View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import Constants from 'expo-constants';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Group, Pill, Row, Screen, Section, Segmented, T, useFeedback, Card } from '../ui/index.js';
import { fmtUptime } from '../format.js';
import { SIREN_MODE_LABEL, scheduleLabel, scheduleTone } from '../lib/view.js';
import { getPushState, setupPushNotifications } from '../pushNotifications.js';

const THEMES = [
  { value: 'system', label: 'System', icon: 'theme-light-dark' },
  { value: 'light', label: 'Light', icon: 'white-balance-sunny' },
  { value: 'dark', label: 'Dark', icon: 'weather-night' },
];

export default function Settings() {
  const nav = useNavigation();
  const { mode, setMode } = useAppTheme();
  const { pi, settings, isDemo, act, client } = useData();
  const { toast } = useFeedback();
  useServerNow(60000);
  const st = pi.status;
  const s = settings?.settings;
  const eff = settings?.effective;
  const homeDays = s?.schedule.home_weekdays.length ?? 0;

  const push = isDemo ? { status: 'demo' } : getPushState();
  const PUSH_LABEL = {
    demo: 'Demo', ready: 'On', unknown: 'Checking…', pi_unreachable: 'Not registered', denied: 'Blocked',
    no_firebase: 'Not set up', error: 'Error', simulator: 'Unsupported', expo_go: 'Unsupported',
  };
  const PUSH_WHY = {
    pi_unreachable: 'The Pi could not be reached when the app opened, so it does not know this phone yet. Open the app on your home Wi-Fi (or with Tailscale on) once.',
    denied: 'Notifications are blocked for this app. Allow them in the phone settings (Apps, Room Security, Notifications).',
    no_firebase: 'This build has no Firebase file, so Android cannot give the app a notification address. See "Notifications" in the README.',
    error: push.detail || 'Could not get a notification address for this phone.',
    simulator: 'Push needs a real phone and the installed app, not an emulator.',
    expo_go: 'Push needs the installed app, not Expo Go.',
  };
  const TEST_WHY = {
    no_devices: 'No phone is registered on the Pi yet. Open the app on your home Wi-Fi (or with Tailscale on) and allow notifications.',
    pi_offline: 'The Pi has no internet, so it cannot send notifications.',
    InvalidCredentials: 'Firebase is not linked to your Expo project yet. See "Notifications" in the README.',
    MessageRateExceeded: 'Too many notifications at once. Try again in a minute.',
    push_disabled: 'Push is switched off in the Pi config (push.enabled).',
  };
  const retryPush = async () => {
    if (isDemo) { toast('Demo: nothing to set up.'); return; }
    await setupPushNotifications(client);
    const st2 = getPushState();
    toast(st2.status === 'ready' ? 'This phone is registered for alerts.' : PUSH_WHY[st2.status] ?? 'Could not register this phone.', st2.status === 'ready' ? 'success' : 'warning');
  };
  const testPush = async () => {
    const r = await act(c => c.testPush());
    if (r.ok) { toast(isDemo ? 'Demo: a test notification would arrive now.' : 'Test notification sent.', 'success'); return; }
    toast(TEST_WHY[r.error] ?? (r.error ? `The Pi could not send it (${r.error}).` : 'Could not reach the Pi.'), 'danger');
  };
  const testSiren = async () => {
    const r = await act(c => c.testSiren());
    toast(r.ok ? 'Siren test started (2 s).' : r.error === 'not_disarmed' ? 'Disarm the room first.' : 'Could not test the siren.', r.ok ? 'success' : 'warning');
  };

  return (
    <Screen title="Settings" subtitle="Make it yours" demo={isDemo} onDemoPress={() => nav.navigate('DataSource')}>
      <Section title="Appearance">
        <Card style={{ gap: 12 }}>
          <Segmented options={THEMES} value={mode} onChange={setMode} />
          <T v="caption" color="muted">Your choice is remembered the next time you open the app.</T>
        </Card>
      </Section>

      <Section title="Automation">
        <Group>
          <Row icon="calendar-clock" tone="primary" title="Schedule" subtitle="Arm and disarm by itself" chevron onPress={() => nav.navigate('Schedule')}
            right={st ? <Pill tone={scheduleTone(st.schedule)} label={scheduleLabel(st.schedule)} dot /> : undefined} />
          <Row icon="home-variant-outline" tone="info" title="Days at home" subtitle="No automatic arming on these days" chevron onPress={() => nav.navigate('DaysAtHome')}
            value={s ? (homeDays ? `${homeDays} weekly` : 'None') : undefined} />
          <Row icon="airplane" tone="info" title="Vacation mode" subtitle="Armed day and night while you are away" chevron onPress={() => nav.navigate('Schedule')}
            value={st?.schedule?.vacation?.active ? 'On' : 'Off'} />
          <Row icon="timer-sand" title="Delays" subtitle="Time to leave and to disarm" chevron onPress={() => nav.navigate('Delays')}
            value={eff ? `${eff.exit_delay_s}s / ${eff.entry_delay_s}s` : undefined} />
        </Group>
      </Section>

      <Section title="Camera and recordings">
        <Group>
          <Row icon="cctv" tone="primary" title="Camera follows the intrusion" subtitle="Turns to the view of the sensor that triggered" chevron onPress={() => nav.navigate('CameraFollow')}
            value={s?.camera ? (s.camera.follow ? 'On' : 'Off') : undefined} />
          <Row icon="google-drive" title="Recordings and storage" subtitle="How long they are kept, space used, clean-up" chevron onPress={() => nav.navigate('Storage')}
            value={s?.cloud ? (s.cloud.retention_days ? `${s.cloud.retention_days} days` : 'Kept') : undefined} />
        </Group>
      </Section>

      <Section title="Alarm">
        <Group>
          <Row icon="bullhorn-outline" tone="warning" title="Siren" subtitle="Sound, silent mode and quiet hours" chevron onPress={() => nav.navigate('SirenSettings')}
            value={SIREN_MODE_LABEL[s?.siren.mode] ?? undefined} />
          <Row icon="volume-high" title="Test the siren" subtitle="Sounds for two seconds, room must be disarmed" onPress={testSiren} />
          <Row icon="bell-ring-outline" title="Send a test notification" subtitle="Check that alerts reach this phone" onPress={testPush} />
          <Row icon="cellphone-message" tone={push.status === 'ready' || push.status === 'demo' ? 'success' : push.status === 'unknown' ? 'neutral' : 'warning'}
            title="Alerts on this phone" subtitle={PUSH_WHY[push.status] ?? 'Alerts reach you even when the app is closed.'}
            value={PUSH_LABEL[push.status]} onPress={retryPush} />
        </Group>
      </Section>

      <Section title="Connection">
        <Group>
          <Row icon={isDemo ? 'flask-outline' : 'raspberry-pi'} tone={isDemo ? 'info' : 'success'} title="Data source"
            subtitle={isDemo ? 'Demo data. Nothing is real.' : 'Your Raspberry Pi'} chevron onPress={() => nav.navigate('DataSource')}
            right={<Pill tone={isDemo ? 'info' : pi.online ? 'success' : 'danger'} label={isDemo ? 'Demo' : pi.online ? 'Connected' : 'Offline'} dot={!isDemo} />} />
        </Group>
      </Section>

      <Section title="About">
        <Group>
          <Row icon="cellphone" title="App version" value={Constants.expoConfig?.version ?? '—'} />
          <Row icon="chip" title="Pi service" value={st ? `${/^\d/.test(st.version) ? 'v' : ''}${st.version}` : '—'} />
          <Row icon="clock-outline" title="Pi uptime" value={st ? fmtUptime(st.uptime_s) : '—'} />
          <Row icon="earth" title="Time zone" value={st?.timezone ?? '—'} />
        </Group>
      </Section>
      <View style={{ height: 4 }} />
    </Screen>
  );
}
