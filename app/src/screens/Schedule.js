import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Button, Card, Choice, DayPicker, Group, Icon, IconButton, Pill, Row, Screen, Section, T, TimeField, Toggle, useFeedback } from '../ui/index.js';
import { fmtDayTime, piDays } from '../format.js';
import { scheduleLabel, scheduleLine, scheduleTone, weekPlan } from '../lib/view.js';

const AWAY = [{ value: 3, label: '3 days' }, { value: 7, label: '1 week' }, { value: 14, label: '2 weeks' }, { value: 21, label: '3 weeks' }, { value: 0, label: 'Until I stop it' }];
const PAUSES = [{ m: 60, label: '1 hour' }, { m: 240, label: '4 hours' }, { m: 1440, label: '24 hours' }];
const WARN = [{ value: 0, label: 'Off' }, { value: 5, label: '5 min' }, { value: 10, label: '10 min' }, { value: 15, label: '15 min' }];
const BUSY = [{ s: 120, label: '2 min' }, { s: 300, label: '5 min' }, { s: 600, label: '10 min' }];

export default function Schedule() {
  const { pi, settings, saveSettings, act } = useData();
  const { toast } = useFeedback();
  const nowS = useServerNow(30000);
  const st = pi.status;
  const tz = st?.timezone;
  const sched = settings?.settings.schedule;
  const [away, setAway] = useState(14);
  const days = useMemo(() => piDays(tz, 7, nowS), [tz, nowS]);
  if (!sched) return <Screen bare><Card><T color="muted">Loading…</T></Card></Screen>;

  const sc = st?.schedule;
  const vac = sc?.vacation?.active;
  const startVacation = async () => {
    const r = await act(c => c.vacation(true, away || undefined));
    toast(r.ok ? 'Vacation mode on. The room stays armed day and night.' : 'Could not start vacation mode.', r.ok ? 'success' : 'danger');
  };
  const endVacation = async () => {
    const r = await act(c => c.vacation(false));
    toast(r.ok ? 'Vacation mode off. The normal schedule is back.' : 'Could not end vacation mode.', r.ok ? 'success' : 'danger');
  };
  const save = async patch => {
    const r = await saveSettings({ schedule: patch });
    if (!r.ok) toast(r.detail ?? 'Could not save the schedule.', 'danger');
  };
  const setWindow = (i, patch) => save({ windows: sched.windows.map((w, j) => (j === i ? { ...w, ...patch } : w)) });
  const removeWindow = i => save({ windows: sched.windows.filter((_, j) => j !== i) });
  const addWindow = () => save({ windows: [...sched.windows, { days: [0, 1, 2, 3, 4], start: '09:00', end: '17:00' }] });
  const plan = weekPlan(sched, days);

  return (
    <Screen bare>
      <Card tone={vac ? 'info' : undefined} style={{ gap: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <Icon name="airplane" color={vac ? 'info' : 'muted'} size={24} />
          <View style={{ flex: 1 }}>
            <T v="heading">Vacation mode</T>
            <T v="small" color="muted">{vac ? scheduleLine(st, tz, nowS) : 'Away for a while? The room stays armed day and night.'}</T>
          </View>
          {vac ? <Pill tone={scheduleTone(sc)} label={scheduleLabel(sc)} dot /> : null}
        </View>
        {vac ? (
          <>
            {sc?.state === 'postponed' && (
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Icon name="timer-sand" size={16} color="warning" /><T v="small" color="warning" style={{ flex: 1 }}>{sc.reason}</T>
              </View>
            )}
            {sc?.state === 'suspended' && (
              <Button label="Arm again" icon="play" size="sm" full={false} onPress={async () => { await act(c => c.resume()); toast('Vacation mode is arming again.', 'success'); }} />
            )}
            <T v="caption" color="muted">Windows and days at home are ignored until it ends. Recordings and alerts are not deleted while you are away.</T>
            <Button label="I am back, end vacation mode" icon="home-import-outline" variant="secondary" onPress={endVacation} />
          </>
        ) : (
          <>
            <T v="smallStrong">How long?</T>
            <Choice options={AWAY} value={away} onChange={setAway} />
            <Button label="Start vacation mode" icon="airplane-takeoff" onPress={startVacation} />
          </>
        )}
      </Card>

      <Card style={{ gap: 12, opacity: vac ? 0.55 : 1 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <View style={{ flex: 1 }}>
            <T v="heading">Automatic arming</T>
            <T v="small" color="muted">{vac ? 'On hold during vacation mode.' : scheduleLine(st, tz, nowS)}</T>
          </View>
          <Toggle value={sched.enabled} onChange={v => save({ enabled: v })} />
        </View>
        {sched.enabled && !vac && <Pill tone={scheduleTone(sc)} label={scheduleLabel(sc)} dot />}
        {!vac && sc?.state === 'postponed' && (
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Icon name="timer-sand" size={16} color="warning" /><T v="small" color="warning" style={{ flex: 1 }}>{sc.reason}</T>
          </View>
        )}
        {!vac && sc?.state === 'suspended' && (
          <Button label="Resume schedule" icon="play" size="sm" full={false} onPress={async () => { await act(c => c.resume()); toast('Schedule resumed.', 'success'); }} />
        )}
        {!vac && sc?.state === 'paused' && (
          <Button label={`Resume now (paused until ${fmtDayTime(sc.paused_until, tz, nowS)})`} icon="play" size="sm" full={false}
            onPress={async () => { await act(c => c.resume()); toast('Schedule resumed.', 'success'); }} />
        )}
      </Card>

      <Section title="Windows">
        {sched.windows.length === 0 ? (
          <Card><T v="small" color="muted">No window yet. Add one to arm the room automatically, for example while you are at work or asleep.</T></Card>
        ) : sched.windows.map((w, i) => {
          const overnight = w.end <= w.start;
          return (
            <Card key={i} style={{ gap: 14 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <T v="bodyStrong">Window {i + 1}</T>
                  {overnight ? <Pill icon="weather-night" label="Overnight" /> : null}
                </View>
                <IconButton icon="trash-can-outline" size={34} tone="danger" label="Remove window" onPress={() => removeWindow(i)} />
              </View>
              <DayPicker value={w.days} onChange={d => setWindow(i, { days: d })} minOne />
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                <View style={{ gap: 6 }}><T v="caption" color="muted">Arms at</T><TimeField value={w.start} onCommit={t => setWindow(i, { start: t })} /></View>
                <View style={{ gap: 6 }}><T v="caption" color="muted">Disarms at</T><TimeField value={w.end} onCommit={t => setWindow(i, { end: t })} /></View>
              </View>
            </Card>
          );
        })}
        <Button label="Add a window" icon="plus" variant="outline" onPress={addWindow} />
      </Section>

      <Section title="Next 7 days">
        <Card style={{ gap: 4 }}>
          {plan.map(d => (
            <View key={d.iso} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 6 }}>
              <T v="smallStrong" color="muted" style={{ width: 52 }}>{d.label} {d.num}</T>
              <Icon name={d.kind === 'armed' ? 'shield-check' : d.kind === 'home' ? 'home-variant-outline' : 'minus'} size={16}
                color={d.kind === 'armed' ? 'primary' : d.kind === 'home' ? 'info' : 'faint'} />
              <T v="small" color={d.kind === 'armed' ? 'text' : 'muted'} style={{ flex: 1 }}>
                {d.kind === 'none' ? 'No window' : d.kind === 'home' ? 'Day at home' : d.times.join(' · ')}
              </T>
            </View>
          ))}
        </Card>
      </Section>

      <Section title="Behaviour">
        <Group>
          <Row title="Disarm when a window ends" subtitle="Only when the schedule armed it" right={<Toggle value={sched.auto_disarm} onChange={v => save({ auto_disarm: v })} />} />
          <Row title="Smart arming" subtitle="Wait while someone is moving in the room, or something is open" right={<Toggle value={sched.smart_arm} onChange={v => save({ smart_arm: v })} />} />
        </Group>
        <Card style={{ gap: 10 }}>
          <T v="smallStrong">Warn me before arming</T>
          <Choice options={WARN} value={sched.pre_arm_warning_min} onChange={v => save({ pre_arm_warning_min: v })} />
          <T v="caption" color="muted">A notification a few minutes before the room arms by itself.</T>
        </Card>
        {sched.smart_arm && (
          <Card style={{ gap: 10 }}>
            <T v="smallStrong">Count as &ldquo;moving&rdquo; for</T>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              {BUSY.map(b => (
                <Button key={b.s} label={b.label} size="sm" variant={sched.busy_s === b.s ? 'primary' : 'secondary'} full={false} onPress={() => save({ busy_s: b.s })} />
              ))}
            </View>
          </Card>
        )}
      </Section>

      {sched.enabled && (
        <Section title="Pause automatic arming">
          <Card style={{ gap: 10 }}>
            <T v="small" color="muted">Guests over, a day off? The schedule does nothing until the pause ends.</T>
            <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
              {PAUSES.map(p => (
                <Button key={p.m} label={p.label} size="sm" variant="secondary" full={false}
                  onPress={async () => { await act(c => c.pause(p.m)); toast(`Schedule paused for ${p.label}.`); }} />
              ))}
            </View>
          </Card>
        </Section>
      )}
    </Screen>
  );
}
