import { View } from 'react-native';
import { useData, useServerNow } from '../data/DataProvider.js';
import { BatteryBar, SignalBars } from '../charts/index.js';
import { Button, Card, EmptyState, Group, Icon, IconTile, Pill, Row, Screen, Section, T, Toggle, useFeedback } from '../ui/index.js';
import { fmtAgo, fmtClock, fmtLeft } from '../format.js';
import { eventMeta, sensorView } from '../lib/view.js';

const BYPASS = {
  contact: [
    { key: 'closed', label: 'Until it is closed', sub: 'Back on automatically, 2 h at most', opts: { minutes: 120, untilClosed: true } },
    { key: '1h', label: 'For 1 hour', sub: 'Then it guards again', opts: { minutes: 60 } },
    { key: 'forever', label: 'Until I turn it on', sub: 'Stays off', opts: {} },
  ],
  motion: [
    { key: '1h', label: 'For 1 hour', sub: 'Then it guards again', opts: { minutes: 60 } },
    { key: '4h', label: 'For 4 hours', sub: 'Then it guards again', opts: { minutes: 240 } },
    { key: 'forever', label: 'Until I turn it on', sub: 'Stays off', opts: {} },
  ],
};

export default function SensorDetail({ route }) {
  const { name } = route.params;
  const { pi, events, client, act, isDemo } = useData();
  const { toast, confirm } = useFeedback();
  const nowS = useServerNow(5000);
  const s = pi.status?.sensors?.find(x => x.name === name);
  if (!s) return <Screen bare><Card><EmptyState icon="help-circle-outline" title="Sensor not found" text="It may not have reported yet." /></Card></Screen>;

  const v = sensorView(s);
  const tz = pi.status.timezone;
  const mine = (events.list ?? []).filter(e => e.text.toLowerCase().includes(s.label.toLowerCase())).slice(0, 6);
  const options = BYPASS[s.kind] ?? BYPASS.contact;

  const turnOn = async () => {
    const r = await act(c => c.setSensor(name, true));
    toast(r.ok ? `${s.label} is guarded again.` : 'Could not change the sensor.', r.ok ? 'success' : 'danger');
  };
  const turnOff = async o => {
    if (pi.status.armed) {
      const go = await confirm({
        title: `Switch ${s.label.toLowerCase()} off?`,
        message: `While it is off, ${s.label.toLowerCase()} will not set off the alarm. Other sensors keep guarding.`,
        confirmLabel: 'Switch off', destructive: true,
      });
      if (!go) return;
    }
    const r = await act(c => c.setSensor(name, false, o.opts));
    toast(r.ok ? `${s.label} is off: ${o.label.toLowerCase()}.` : 'Could not change the sensor.', r.ok ? 'success' : 'danger');
  };

  return (
    <Screen bare>
      <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
        <IconTile name={v.icon} tone={v.tone} size={56} />
        <View style={{ flex: 1, gap: 4 }}>
          <T v="title">{s.label}</T>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Pill tone={v.tone} label={v.text} dot />
            {s.online === false ? <Pill tone="danger" label="Offline" /> : null}
            {s.tamper ? <Pill tone="danger" label="Tamper" icon="alert-octagon" /> : null}
          </View>
        </View>
      </Card>

      <Group>
        <Row icon="battery-outline" title="Battery" right={<BatteryBar value={s.battery} />} />
        <Row icon="signal" title="Signal" right={<SignalBars value={s.linkquality} />} value={s.linkquality != null ? `${s.linkquality}/255` : undefined} />
        <Row icon="clock-outline" title="Last seen" value={s.last_seen ? `${fmtAgo(s.last_seen, nowS)} · ${fmtClock(s.last_seen, tz)}` : '—'} />
        <Row icon="tag-outline" title="Type" value={s.kind === 'motion' ? 'Motion sensor' : 'Contact sensor'} />
      </Group>

      <Section title="Guarding">
        <Card style={{ gap: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={{ flex: 1 }}>
              <T v="bodyStrong">{v.off ? 'Switched off' : 'Guarding the room'}</T>
              <T v="small" color="muted">
                {v.off
                  ? s.bypass_until_closed ? `Back on when closed${s.bypass_until ? `, or in ${fmtLeft(s.bypass_until - nowS)}` : ''}`
                    : s.bypass_until ? `Back on in ${fmtLeft(s.bypass_until - nowS)}` : 'Stays off until you turn it on'
                  : 'An alert from this sensor starts the entry countdown or the alarm.'}
              </T>
            </View>
            {v.off ? <Toggle value={false} onChange={turnOn} /> : null}
          </View>
          {!v.off && (
            <View style={{ gap: 8 }}>
              <T v="caption" color="muted">Switch off temporarily</T>
              {options.map(o => (
                <Button key={o.key} label={o.label} icon="eye-off-outline" variant="outline" size="sm" onPress={() => turnOff(o)} style={{ justifyContent: 'flex-start' }} />
              ))}
            </View>
          )}
          <View style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }}>
            <Icon name="shield-alert-outline" size={15} color="faint" />
            <T v="caption" color="faint" style={{ flex: 1 }}>Tamper alerts stay active even when a sensor is switched off.</T>
          </View>
        </Card>
      </Section>

      {isDemo && client.simulate && (
        <Section title="Demo controls">
          <Card style={{ gap: 10 }}>
            <T v="small" color="muted">Try how the system reacts, without touching anything.</T>
            <View style={{ flexDirection: 'row', gap: 10 }}>
              <Button label={s.kind === 'motion' ? 'Simulate movement' : 'Simulate opening'} icon="flash-outline" variant="secondary" style={{ flex: 1 }}
                onPress={async () => { await act(c => c.simulate(name)); toast('Event sent to the demo system.'); }} />
              {s.kind === 'contact' && <Button label="Close it" icon="door-closed" variant="outline" style={{ flex: 1 }} onPress={() => act(c => c.closeAll())} />}
            </View>
          </Card>
        </Section>
      )}

      {mine.length > 0 && (
        <Section title="Recent activity">
          <Group>
            {mine.map(e => {
              const m = eventMeta(e.kind);
              return <Row key={e.id} icon={m.icon} tone={m.tone} title={e.text} subtitle={fmtAgo(e.ts, nowS)} />;
            })}
          </Group>
        </Section>
      )}
    </Screen>
  );
}
