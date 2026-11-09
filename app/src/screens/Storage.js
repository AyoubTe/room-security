import { View } from 'react-native';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Button, Card, Choice, Group, Icon, Row, Screen, Section, T, useFeedback } from '../ui/index.js';
import { fmtDayTime } from '../format.js';
import { RETENTION_CHOICES, cleanupLine, fmtBytes } from '../lib/view.js';

/** How long recordings and alerts are kept, how much space they use, and a manual clean-up. */
export default function Storage() {
  const { pi, settings, saveSettings, act } = useData();
  const { toast, confirm } = useFeedback();
  const nowS = useServerNow(60000);
  const st = pi.status;
  const r = st?.retention;
  const tz = st?.timezone;
  const days = settings?.settings.cloud?.retention_days;
  if (!r || days == null) return <Screen bare><Card><T color="muted">Loading…</T></Card></Screen>;

  const setDays = async v => {
    const res = await saveSettings({ cloud: { retention_days: v } });
    if (!res.ok) toast(res.detail ?? 'Could not save.', 'danger');
  };
  const cleanNow = async () => {
    const go = await confirm({
      title: 'Clean up now?',
      message: days ? `Recordings and alerts older than ${days} days will be deleted for good. This also works while vacation mode is on.` : 'Recordings are set to be kept for ever, so nothing will be deleted.',
      confirmLabel: days ? 'Delete old ones' : 'OK',
      destructive: !!days,
    });
    if (!go || !days) return;
    const res = await act(c => c.cleanup());
    toast(res.ok ? cleanupLine(res.result) + '.' : 'Could not clean up. Is the Pi reachable?', res.ok ? 'success' : 'danger');
  };

  return (
    <Screen bare>
      {r.hold && (
        <Card tone="info" style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
          <Icon name="airplane" color="info" />
          <T v="small" style={{ flex: 1 }}>Vacation mode is on, so nothing is deleted until you are back.</T>
        </Card>
      )}

      <Card style={{ gap: 12 }}>
        <View>
          <T v="heading">Keep recordings and alerts for</T>
          <T v="small" color="muted">Older ones are deleted every night to free space on your cloud storage.</T>
        </View>
        <Choice options={RETENTION_CHOICES} value={days} onChange={setDays} />
      </Card>

      <Section title="Space used">
        <Group>
          <Row icon="google-drive" tone="primary" title="Cloud storage" subtitle={r.usage ? `${r.usage.count} files` : 'Not measured yet'} value={r.usage ? fmtBytes(r.usage.bytes) : '—'} />
          <Row icon="broom" title="Last clean-up" subtitle={cleanupLine(r.last)} value={r.last ? fmtDayTime(r.last.at, tz, nowS) : undefined} />
          <Row icon="clock-outline" title="Runs every night at" value={r.at} />
        </Group>
      </Section>

      <Button label="Clean up now" icon="broom" variant="secondary" onPress={cleanNow} />
      <T v="caption" color="faint" style={{ paddingHorizontal: 4 }}>
        Deleted recordings do not go to the Drive bin, so the space is freed straight away.
      </T>
    </Screen>
  );
}
