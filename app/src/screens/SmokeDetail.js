import { useEffect, useState } from 'react';
import { Image, View } from 'react-native';
import { useIsFocused } from '@react-navigation/native';
import { useData } from '../data/DataProvider.js';
import { Button, Card, EmptyState, Group, IconTile, Pill, Row, Screen, Section, T, useFeedback } from '../ui/index.js';
import { SignalBars } from '../charts/index.js';

export default function SmokeDetail() {
  const { smoke, client, act, isDemo, refresh } = useData();
  const { toast } = useFeedback();
  const focused = useIsFocused();
  const d = smoke.device;
  const [still, setStill] = useState(() => client.smokeSnapshotSource());
  const [alertPhoto, setAlertPhoto] = useState(null);

  useEffect(() => {
    if (!focused) return undefined;
    const id = setInterval(() => setStill(client.smokeSnapshotSource()), 6000);
    return () => clearInterval(id);
  }, [client, focused]);

  const rssi = d ? Math.max(0, Math.min(255, Math.round(((d.rssi + 95) / 55) * 255))) : null;

  return (
    <Screen bare onRefresh={refresh}>
      <Card tone={d?.smokeDetected ? 'danger' : 'neutral'} style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
        <IconTile name="smoke-detector-variant" tone={d?.smokeDetected ? 'danger' : smoke.online ? 'success' : 'neutral'} size={56} />
        <View style={{ flex: 1, gap: 4 }}>
          <T v="title">{d?.smokeDetected ? 'Smoke detected' : d ? 'Air is clear' : 'Not reachable'}</T>
          <Pill dot tone={smoke.online ? 'success' : 'danger'} label={smoke.online ? 'Online' : 'Offline'} />
        </View>
      </Card>

      {d ? (
        <>
          <Section title="Camera">
            <Image source={still} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: 16, backgroundColor: '#000' }} resizeMode="cover" />
            <View style={{ flexDirection: 'row', gap: 12 }}>
              <Button label="Refresh" icon="image-refresh" variant="secondary" style={{ flex: 1 }} onPress={() => setStill(client.smokeSnapshotSource())} />
              <Button label="Last alert photo" icon="image-outline" variant="outline" style={{ flex: 1 }} onPress={() => setAlertPhoto(client.smokeAlertPhotoSource())} />
            </View>
            {alertPhoto && <Image source={alertPhoto} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: 16, backgroundColor: '#000' }} resizeMode="cover" />}
          </Section>

          <Group>
            <Row icon="gas-cylinder" title="Gas sensor" value={d.sensorReady ? 'Ready' : 'Warming up'} tone={d.sensorReady ? 'success' : 'warning'} />
            <Row icon="wifi" title="Wi-Fi signal" value={`${d.rssi} dBm`} right={<SignalBars value={rssi} />} />
            <Row icon="clock-outline" title="Uptime" value={d.uptime} />
            <Row icon="memory" title="Free memory" value={d.heap} />
            <Row icon="chip" title="Firmware" value={d.fw ?? '—'} />
          </Group>
        </>
      ) : (
        <Card><EmptyState icon="wifi-off" title="The detector does not answer" text="It must be on the same Wi-Fi as your phone. Away from home it is only reachable through your VPN." /></Card>
      )}

      {isDemo && client.simulate && (
        <Section title="Demo controls">
          <Card style={{ gap: 10 }}>
            <T v="small" color="muted">Raise a smoke alert for 20 seconds to see how the app reacts.</T>
            <Button label="Simulate smoke" icon="smoke" variant="secondary" onPress={async () => { await act(c => c.simulate('smoke')); toast('Smoke alert sent to the demo detector.', 'warning'); }} />
          </Card>
        </Section>
      )}
    </Screen>
  );
}
