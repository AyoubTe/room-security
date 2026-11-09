import { View } from 'react-native';
import { useData } from '../data/DataProvider.js';
import { Card, Choice, Icon, Screen, Section, Segmented, T, TimeField, useFeedback } from '../ui/index.js';

const MODES = [
  { value: 'on', label: 'On', icon: 'volume-high' },
  { value: 'quiet_hours', label: 'Quiet hours', icon: 'weather-night' },
  { value: 'silent', label: 'Silent', icon: 'volume-off' },
];
const HELP = {
  on: 'The siren sounds whenever the alarm goes off.',
  quiet_hours: 'Silent during the hours below, loud the rest of the day. The alarm, recording and notifications still happen.',
  silent: 'The siren never sounds. You still get notifications and the camera records.',
};
const VOLUMES = [{ value: 'low', label: 'Low' }, { value: 'medium', label: 'Medium' }, { value: 'high', label: 'High' }, { value: 'max', label: 'Max' }];
const DURATIONS = [{ value: 30, label: '30 s' }, { value: 60, label: '1 min' }, { value: 120, label: '2 min' }, { value: 300, label: '5 min' }];

export default function SirenSettings() {
  const { settings, saveSettings, pi } = useData();
  const { toast } = useFeedback();
  const siren = settings?.settings.siren;
  if (!siren) return <Screen bare><Card><T color="muted">Loading…</T></Card></Screen>;
  const dur = siren.duration_s ?? settings.effective.siren_duration_s;

  const save = async patch => {
    const r = await saveSettings({ siren: patch });
    if (!r.ok) toast(r.detail ?? 'Could not save.', 'danger');
  };

  return (
    <Screen bare>
      <Section title="Mode">
        <Card style={{ gap: 12 }}>
          <Segmented options={MODES} value={siren.mode} onChange={m => save({ mode: m })} />
          <T v="small" color="muted">{HELP[siren.mode]}</T>
        </Card>
      </Section>

      {siren.mode === 'quiet_hours' && (
        <Section title="Quiet hours">
          <Card style={{ flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <View style={{ gap: 6 }}><T v="caption" color="muted">From</T><TimeField value={siren.quiet_hours.start} onCommit={t => save({ quiet_hours: { start: t } })} /></View>
            <View style={{ gap: 6 }}><T v="caption" color="muted">Until</T><TimeField value={siren.quiet_hours.end} onCommit={t => save({ quiet_hours: { end: t } })} /></View>
          </Card>
        </Section>
      )}

      <Section title="Volume">
        <Card><Choice options={VOLUMES} value={siren.volume} onChange={v => save({ volume: v })} /></Card>
      </Section>

      <Section title="Ring for">
        <Card style={{ gap: 10 }}>
          <Choice options={DURATIONS} value={dur} onChange={v => save({ duration_s: v })} />
          <T v="caption" color="muted">Then the siren stops by itself. Recording continues until the incident ends.</T>
        </Card>
      </Section>

      {pi.status?.siren_active && (
        <Card tone="warning" style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}>
          <Icon name="alert" color="warning" /><T v="small" color="muted" style={{ flex: 1 }}>The siren is sounding now. Silence it from Home.</T>
        </Card>
      )}
    </Screen>
  );
}
