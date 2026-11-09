import { View } from 'react-native';
import { useData } from '../data/DataProvider.js';
import { SENTINEL_CONFIGURED, SENTINEL_HOST } from '../config.js';
import { Button, Card, Group, Icon, IconTile, Pill, Row, Screen, Section, T, useFeedback } from '../ui/index.js';

function Option({ icon, title, text, active, onPress, tone }) {
  return (
    <Card tone={active ? tone : 'neutral'} onPress={onPress} style={{ flexDirection: 'row', gap: 14, alignItems: 'center' }}>
      <IconTile name={icon} tone={active ? tone : 'neutral'} size={46} />
      <View style={{ flex: 1, gap: 2 }}>
        <T v="bodyStrong">{title}</T>
        <T v="small" color="muted">{text}</T>
      </View>
      {active ? <Pill tone={tone} label="In use" /> : <Icon name="chevron-right" color="faint" />}
    </Card>
  );
}

export default function DataSource() {
  const { source, chooseSource, isDemo, client, act, pi } = useData();
  const { toast, confirm } = useFeedback();

  const toLive = async () => {
    if (!SENTINEL_CONFIGURED) {
      await confirm({
        title: 'Pi not set up yet',
        message: 'Open src/config.js, set SENTINEL_HOST and SENTINEL_TOKEN to your Pi, and rebuild the app. Until then the app stays in demo mode.',
        confirmLabel: 'OK', cancelLabel: 'Close',
      });
      return;
    }
    chooseSource('live');
    toast('Connecting to your Pi…');
  };

  return (
    <Screen bare>
      <Card style={{ flexDirection: 'row', gap: 10 }}>
        <Icon name="information-outline" color="faint" size={18} />
        <T v="small" color="muted" style={{ flex: 1 }}>Demo mode fills every screen with realistic sample data so you can explore the app before the Raspberry Pi is installed. You can switch at any time.</T>
      </Card>

      <Section title="Choose">
        <Option icon="flask-outline" tone="info" title="Demo data" text="Two weeks of invented history. Everything is simulated."
          active={source === 'demo'} onPress={() => { chooseSource('demo'); toast('Demo mode on.'); }} />
        <Option icon="raspberry-pi" tone="success" title="My Raspberry Pi" text={SENTINEL_CONFIGURED ? SENTINEL_HOST : 'Not set up yet: fill in src/config.js'}
          active={source === 'live'} onPress={toLive} />
      </Section>

      {!isDemo && (
        <Group>
          <Row icon="lan-connect" title="Status" value={pi.online ? 'Connected' : pi.error ?? 'Offline'} tone={pi.online ? 'success' : 'danger'} />
          <Row icon="ip-network-outline" title="Address" value={SENTINEL_HOST} />
        </Group>
      )}

      {isDemo && client.reset && (
        <Section title="Demo controls">
          <Card style={{ gap: 10 }}>
            <T v="small" color="muted">Put the demo back to its starting point: fresh history, default settings.</T>
            <Button label="Reset demo data" icon="restore" variant="secondary" onPress={async () => {
              const go = await confirm({ title: 'Reset the demo?', message: 'Your demo changes are lost. Nothing real is affected.', confirmLabel: 'Reset', destructive: true });
              if (go) { await act(c => c.reset()); toast('Demo data reset.', 'success'); }
            }} />
          </Card>
        </Section>
      )}
    </Screen>
  );
}
