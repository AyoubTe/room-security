import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { tint } from '../theme/tokens.js';
import { BarChart } from '../charts/index.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Button, Card, EmptyState, Group, Hero, Icon, IconTile, Metric, Pill, Row, Screen, Section, StatusPill, T, useFeedback } from '../ui/index.js';
import { fmtAgo, fmtDate, fmtHours, fmtLeft, greeting, piDays } from '../format.js';
import {
  SIREN_MODE_LABEL, eventMeta, scheduleLabel, scheduleLine, scheduleTone, stateView, weekPlan,
} from '../lib/view.js';

const SIREN_CYCLE = ['on', 'silent', 'quiet_hours'];

function QuickAction({ icon, label, sub, tone = 'neutral', onPress, disabled }) {
  const { colors } = useAppTheme();
  return (
    <Card onPress={disabled ? undefined : onPress} padding={14} style={{ width: '48%', gap: 10, opacity: disabled ? 0.5 : 1 }} label={label}>
      <IconTile name={icon} tone={tone} size={36} />
      <View style={{ gap: 2 }}>
        <T v="bodyStrong">{label}</T>
        <T v="caption" color={tone === 'neutral' ? 'muted' : tone} numberOfLines={1} style={tone === 'neutral' ? undefined : { color: colors[tone] }}>{sub}</T>
      </View>
    </Card>
  );
}

function WeekStrip({ plan }) {
  const { colors } = useAppTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 6 }}>
      {plan.map((d, i) => {
        const armed = d.kind === 'armed';
        const home = d.kind === 'home';
        return (
          <View key={d.iso} style={{ flex: 1, alignItems: 'center', gap: 6 }}>
            <T v="caption" color={i === 0 ? 'primary' : 'faint'}>{d.label[0]}</T>
            <View style={{
              width: '100%', aspectRatio: 0.72, borderRadius: 10, alignItems: 'center', justifyContent: 'center',
              backgroundColor: armed ? tint(colors.primary, 0.16) : home ? tint(colors.info, 0.14) : colors.surfaceAlt,
              borderWidth: i === 0 ? 1.5 : 0, borderColor: colors.primary,
            }}>
              <Icon name={armed ? 'shield-check' : home ? 'home-variant-outline' : 'minus'} size={16} color={armed ? 'primary' : home ? 'info' : 'faint'} />
            </View>
            <T v="caption" color={i === 0 ? 'text' : 'muted'} style={{ fontVariant: ['tabular-nums'] }}>{d.num}</T>
          </View>
        );
      })}
    </View>
  );
}

export default function Home() {
  const nav = useNavigation();
  const { colors } = useAppTheme();
  const { toast, confirm } = useFeedback();
  const { pi, smoke, events, insights, settings, isDemo, act, refresh } = useData();
  const nowS = useServerNow();
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null);

  const st = pi.status;
  const tz = st?.timezone;
  const remaining = st?.remaining_s != null && pi.at ? Math.max(0, st.remaining_s - Math.floor((nowS - st.server_time))) : null;
  const view = stateView(st, remaining);
  const armed = !!st?.armed;
  const sc = st?.schedule;

  const run = async fn => {
    setBusy(true);
    const res = await fn();
    setBusy(false);
    return res;
  };

  const onArm = async () => {
    const res = await run(() => act(c => c.arm(false)));
    if (res.ok) return;
    if (res.error === 'open_sensors') {
      const go = await confirm({
        title: 'Something is open',
        message: `${(res.open || []).join(', ')} ${res.open?.length > 1 ? 'are' : 'is'} open. Arm anyway? An open sensor cannot trigger until it is closed and opened again.`,
        confirmLabel: 'Arm anyway', destructive: true,
      });
      if (go) await run(() => act(c => c.arm(true)));
    } else toast(res.error === 'network' ? 'Could not reach the Pi.' : `Could not arm (${res.error}).`, 'danger');
  };

  const onDisarm = async () => {
    const res = await run(() => act(c => c.disarm()));
    if (!res.ok) toast('Could not disarm. Try again.', 'danger');
    else if (res.schedule_suspended) toast('Disarmed. The schedule will not re-arm until this window ends.');
  };

  const onSilence = async () => {
    const res = await run(() => act(c => c.silence()));
    toast(res.ok ? 'Siren silenced. Recording continues.' : 'The siren was not sounding.', res.ok ? 'success' : 'neutral');
  };

  const windowSensor = st?.sensors?.find(s => /window/i.test(s.name + s.label));
  const onWindow = async () => {
    if (!windowSensor) return;
    if (windowSensor.enabled === false) {
      await act(c => c.setSensor(windowSensor.name, true));
      toast(`${windowSensor.label} is guarded again.`, 'success');
    } else {
      await act(c => c.setSensor(windowSensor.name, false, { minutes: 120, untilClosed: true }));
      toast(`${windowSensor.label} is off until it is closed (2 h at most).`);
    }
  };

  const homeToday = sc?.skipped_now === 'date';
  const onHomeToday = async () => {
    const res = await act(c => c.skipDay('today', !homeToday));
    toast(res.ok ? (homeToday ? 'Today is a normal day again.' : 'Day at home: no automatic arming today.') : 'Could not update the schedule.', res.ok ? 'success' : 'danger');
  };

  const onSiren = async () => {
    const cur = st?.siren_mode ?? 'on';
    const next = SIREN_CYCLE[(SIREN_CYCLE.indexOf(cur) + 1) % SIREN_CYCLE.length];
    const res = await act(c => c.saveSettings({ siren: { mode: next } }));
    toast(res.ok ? `Siren: ${SIREN_MODE_LABEL[next]}` : 'Could not change the siren mode.', res.ok ? 'success' : 'danger');
  };

  const today = insights?.days?.[insights.days.length - 1];
  const sensors = st?.sensors ?? [];
  const deviceCount = sensors.length + 2;
  const deviceOk = sensors.filter(s => s.online !== false).length + (st?.camera_ok ? 1 : 0) + (smoke.online ? 1 : 0);
  const lowBattery = sensors.filter(s => s.battery != null && s.battery <= 20).length;
  const cloud = st?.cloud;
  const days = useMemo(() => piDays(tz, 7, nowS), [tz, nowS]);
  const plan = settings ? weekPlan(settings.settings.schedule, days) : null;

  const series = [
    { key: 'alarms', color: colors.danger, label: 'Alarms' },
    { key: 'triggers', color: colors.warning, label: 'Triggers' },
  ];
  const chartData = (insights?.days ?? []).map(d => ({ label: String(Number(d.date.slice(8))), values: { alarms: d.alarms, triggers: d.triggers }, date: d.date }));
  const sel = selected != null ? insights.days[selected] : null;

  const recent = (events.list ?? []).slice(0, 4);
  const now = new Date();

  return (
    <Screen
      title={greeting(now)}
      subtitle={now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
      right={<StatusPill online={pi.online} label={pi.online ? (isDemo ? 'Demo' : 'Pi online') : 'Pi offline'} />}
      demo={isDemo}
      onDemoPress={() => nav.navigate('DataSource')}
      onRefresh={refresh}>
      {!pi.online && pi.loaded && (
        <Card tone="warning" style={{ gap: 10 }}>
          <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
            <IconTile name="wifi-off" tone="warning" />
            <View style={{ flex: 1 }}>
              <T v="bodyStrong">Cannot reach the Pi</T>
              <T v="small" color="muted">{pi.error || 'Check the network.'} Away from home, turn Tailscale on.</T>
            </View>
          </View>
          <Button label="Retry" variant="secondary" size="sm" full={false} icon="refresh" onPress={refresh} />
        </Card>
      )}

      {/* ---------------------------------------------------------------- status */}
      <Hero colors={colors[view.wash]} tone={view.tone}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
          <IconTile name={view.icon} tone={view.tone} size={56} />
          <View style={{ flex: 1, gap: 3 }}>
            <T v="display" style={view.tone !== 'neutral' && view.tone !== 'primary' ? { color: colors[view.tone] } : undefined}>{view.title}</T>
            <T v="small" color="muted">{view.sub}</T>
          </View>
        </View>
        {st?.armed_by && st.state === 'armed' ? <Pill label={st.armed_by === 'schedule' ? 'Armed by schedule' : 'Armed by you'} icon={st.armed_by === 'schedule' ? 'calendar-clock' : 'account'} /> : null}
        {st?.state === 'alarm' && st.event ? <Pill tone="danger" solid label={`Started ${fmtAgo(st.event.started, nowS)}`} /> : null}
        {st && (
          <View style={{ gap: 10 }}>
            {st.siren_active && <Button label="Silence siren" icon="volume-off" variant="danger" size="lg" loading={busy} onPress={onSilence} />}
            {armed
              ? <Button label={st.state === 'exit_delay' ? 'Cancel arming' : 'Disarm'} icon="lock-open-variant" size="lg" loading={busy}
                  variant={st.state === 'entry_delay' || (st.state === 'alarm' && !st.siren_active) ? 'danger' : 'secondary'} onPress={onDisarm} />
              : <Button label="Arm the room" icon="lock" size="lg" loading={busy} onPress={onArm} disabled={!pi.online} />}
          </View>
        )}
        {(sc?.enabled || sc?.vacation?.active) && (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Icon name={sc.vacation?.active ? 'airplane' : 'calendar-clock'} size={15} color={sc.vacation?.active ? 'info' : 'muted'} />
            <T v="caption" color="muted" style={{ flex: 1 }} numberOfLines={2}>{scheduleLine(st, tz, nowS)}</T>
          </View>
        )}
      </Hero>

      {/* ---------------------------------------------------------------- quick actions */}
      <Section title="Quick actions">
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
          <QuickAction icon="video-outline" label="Live camera" sub="Watch now" onPress={() => nav.navigate('Camera')} />
          {windowSensor && (
            <QuickAction
              icon={windowSensor.enabled === false ? 'window-open-variant' : 'window-closed-variant'}
              label={windowSensor.enabled === false ? 'Window is off' : 'Air the room'}
              sub={windowSensor.enabled === false ? (windowSensor.bypass_until ? `Back on in ${fmtLeft(windowSensor.bypass_until - nowS)}` : 'Tap to turn on') : 'Switch window off'}
              tone={windowSensor.enabled === false ? 'info' : 'neutral'}
              onPress={onWindow}
            />
          )}
          {sc?.enabled && (
            <QuickAction
              icon={homeToday ? 'home-variant' : 'home-variant-outline'}
              label="At home today"
              sub={homeToday ? 'On: no auto-arm' : sc.skipped_now === 'weekday' ? 'Weekly home day' : 'Off'}
              tone={homeToday || sc.skipped_now === 'weekday' ? 'info' : 'neutral'}
              onPress={sc.skipped_now === 'weekday' ? () => nav.navigate('DaysAtHome') : onHomeToday}
            />
          )}
          <QuickAction
            icon={st?.siren_mode === 'silent' ? 'volume-off' : 'volume-high'}
            label="Siren"
            sub={SIREN_MODE_LABEL[st?.siren_mode] ?? '—'}
            tone={st?.siren_mode === 'silent' ? 'warning' : 'neutral'}
            onPress={onSiren}
          />
        </View>
      </Section>

      {/* ---------------------------------------------------------------- metrics */}
      <Section title="Overview" action="Insights" onAction={() => nav.navigate('Activity', { tab: 'insights' })}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
          <Metric icon="shield-check" label="Armed today" tone="success"
            value={today ? fmtHours(today.armed_s) : '—'} sub={insights ? `${insights.totals.armed_pct}% of the last 14 days` : 'No data yet'} />
          <Metric icon="alarm-light-outline" label="Alarms · 14 days" tone={insights?.totals.alarms ? 'danger' : 'neutral'}
            value={insights ? String(insights.totals.alarms) : '—'}
            sub={insights?.last_alarm ? `Last: ${fmtAgo(insights.last_alarm.ts, nowS)}` : 'None recorded'} />
          <Metric icon="devices" label="Devices online" tone={deviceOk === deviceCount ? 'success' : 'warning'}
            value={`${deviceOk}/${deviceCount}`} unit="" sub={lowBattery ? `${lowBattery} low battery` : 'All healthy'}
            onPress={() => nav.navigate('Devices')} />
          <Metric icon="cloud-check-outline" label="Cloud backup" tone={!cloud || !cloud.configured ? 'neutral' : cloud.last_error ? 'warning' : 'success'}
            value={!cloud ? '—' : !cloud.configured ? 'Off' : cloud.pending_files ? `${cloud.pending_files}` : 'OK'}
            unit={cloud?.configured && cloud.pending_files ? 'pending' : ''} sub={!cloud ? '' : !cloud.configured ? 'Clips stay on the Pi' : cloud.pending_files ? `${cloud.pending_mb} MB uploading` : 'Everything is uploaded'} />
        </View>
      </Section>

      {/* ---------------------------------------------------------------- schedule */}
      {settings && (
        <Section title="Schedule" action="Edit" onAction={() => nav.navigate('Schedule')}>
          <Card style={{ gap: 14 }} onPress={() => nav.navigate('Schedule')}>
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
              <T v="bodyStrong">{sc?.vacation?.active ? 'Vacation' : 'This week'}</T>
              <Pill tone={scheduleTone(sc)} label={scheduleLabel(sc)} dot />
            </View>
            {sc?.vacation?.active
              ? <T v="small" color="muted">Vacation mode: armed day and night. The weekly plan is on hold.</T>
              : plan && <WeekStrip plan={plan} />}
            <View style={{ flexDirection: 'row', gap: 14 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Icon name="shield-check" size={14} color="primary" /><T v="caption" color="muted">Armed</T>
              </View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Icon name="home-variant-outline" size={14} color="info" /><T v="caption" color="muted">Day at home</T>
              </View>
            </View>
          </Card>
        </Section>
      )}

      {/* ---------------------------------------------------------------- chart */}
      <Section title="Alerts · last 14 days" action="Details" onAction={() => nav.navigate('Activity', { tab: 'insights' })}>
        <Card style={{ gap: 12 }}>
          {chartData.length ? (
            <>
              <View style={{ minHeight: 34, justifyContent: 'center' }}>
                {sel ? (
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                    <T v="bodyStrong">{fmtDate(sel.date)}</T>
                    <T v="small" color="muted">{sel.alarms} alarm{sel.alarms === 1 ? '' : 's'} · {sel.triggers} trigger{sel.triggers === 1 ? '' : 's'}</T>
                  </View>
                ) : (
                  <View style={{ flexDirection: 'row', gap: 16 }}>
                    {series.map(s => (
                      <View key={s.key} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: s.color }} /><T v="caption" color="muted">{s.label}</T>
                      </View>
                    ))}
                    <T v="caption" color="faint" style={{ marginLeft: 'auto' }}>Tap a bar</T>
                  </View>
                )}
              </View>
              <BarChart data={chartData} series={series} selected={selected} onSelect={setSelected} />
            </>
          ) : (
            <EmptyState icon="chart-bar" title="No activity yet" text="Alarms and triggers will be charted here once the system has been running for a day." />
          )}
        </Card>
      </Section>

      {/* ---------------------------------------------------------------- smoke */}
      <Section title="Smoke detector">
        <Card onPress={() => nav.navigate('SmokeDetail')} style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
          <IconTile name="smoke-detector-variant" tone={smoke.device?.smokeDetected ? 'danger' : smoke.online ? 'success' : 'neutral'} size={46} />
          <View style={{ flex: 1, gap: 2 }}>
            <T v="bodyStrong">{smoke.device?.smokeDetected ? 'Smoke detected' : smoke.device ? 'Air clear' : 'Not reachable'}</T>
            <T v="small" color="muted">{smoke.device ? `${smoke.device.name} · ${smoke.device.rssi} dBm · up ${smoke.device.uptime}` : 'The ESP32 does not answer.'}</T>
          </View>
          <Icon name="chevron-right" color="faint" />
        </Card>
      </Section>

      {/* ---------------------------------------------------------------- recent */}
      <Section title="Recent activity" action="See all" onAction={() => nav.navigate('Activity')}>
        {recent.length ? (
          <Group>
            {recent.map(e => {
              const m = eventMeta(e.kind);
              return (
                <Row key={e.id} icon={m.icon} tone={m.tone} title={e.text} subtitle={fmtAgo(e.ts, nowS)}
                  onPress={e.event_id && (e.kind === 'alarm' || e.kind === 'trigger') ? () => nav.navigate('EventDetail', { eventId: e.event_id }) : undefined}
                  chevron={!!e.event_id && (e.kind === 'alarm' || e.kind === 'trigger')} />
              );
            })}
          </Group>
        ) : (
          <Card><EmptyState icon="timeline-clock-outline" title="Nothing yet" text="Arming, alarms and sensor changes will appear here." /></Card>
        )}
      </Section>
    </Screen>
  );
}
