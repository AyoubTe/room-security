import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { BarChart, HBars, HourStrip, Ring } from '../charts/index.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Card, Choice, EmptyState, Group, Metric, Row, Screen, Section, Segmented, T } from '../ui/index.js';
import { dayLabel, dayKey, fmtAgo, fmtClock, fmtDate, fmtHours } from '../format.js';
import { EVENT_FILTERS, eventCategory, eventMeta } from '../lib/view.js';

function Timeline({ nav }) {
  const { events, pi } = useData();
  const nowS = useServerNow(10000);
  const tz = pi.status?.timezone;
  const [filter, setFilter] = useState('all');

  const groups = useMemo(() => {
    const list = (events.list ?? []).filter(e => filter === 'all' || eventCategory(e.kind) === filter);
    const out = [];
    list.forEach(e => {
      const k = dayKey(e.ts, tz);
      const last = out[out.length - 1];
      if (last && last.key === k) last.items.push(e);
      else out.push({ key: k, label: dayLabel(e.ts, tz, nowS), items: [e] });
    });
    return out;
  }, [events.list, filter, tz, nowS]);

  return (
    <>
      <Choice options={EVENT_FILTERS} value={filter} onChange={setFilter} />
      {events.list === null ? (
        <Card><EmptyState icon={events.error ? 'wifi-off' : 'timeline-clock-outline'} title={events.error ? 'Cannot reach the Pi' : 'Loading…'} text={events.error ?? undefined} /></Card>
      ) : groups.length === 0 ? (
        <Card><EmptyState icon="timeline-clock-outline" title="Nothing here" text="No events match this filter yet." /></Card>
      ) : groups.map(g => (
        <Section key={g.key} title={g.label}>
          <Group>
            {g.items.map(e => {
              const m = eventMeta(e.kind);
              const link = !!e.event_id && (e.kind === 'alarm' || e.kind === 'trigger');
              return (
                <Row key={e.id} icon={m.icon} tone={m.tone} title={e.text} subtitle={fmtClock(e.ts, tz)}
                  titleColor={e.kind === 'alarm' ? 'danger' : 'text'}
                  onPress={link ? () => nav.navigate('EventDetail', { eventId: e.event_id }) : undefined} chevron={link} />
              );
            })}
          </Group>
        </Section>
      ))}
    </>
  );
}

function Insights() {
  const { colors } = useAppTheme();
  const { insights } = useData();
  const nowS = useServerNow(30000);
  const [sel, setSel] = useState(null);

  if (!insights) return <Card><EmptyState icon="chart-box-outline" title="No data yet" text="Insights appear once the system has been running." /></Card>;
  const t = insights.totals;
  const series = [
    { key: 'alarms', color: colors.danger, label: 'Alarms' },
    { key: 'triggers', color: colors.warning, label: 'Triggers' },
  ];
  const data = insights.days.map(d => ({ label: String(Number(d.date.slice(8))), values: { alarms: d.alarms, triggers: d.triggers } }));
  const day = sel != null ? insights.days[sel] : null;
  const peak = insights.hours.indexOf(Math.max(...insights.hours));
  const labelOf = name => name.charAt(0).toUpperCase() + name.slice(1);
  const falseAlarms = Math.max(0, t.triggers - t.alarms);

  return (
    <>
      <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 18 }}>
        <Ring progress={t.armed_pct / 100} size={92} stroke={10} color="success">
          <T v="metricSm">{Math.round(t.armed_pct)}%</T>
        </Ring>
        <View style={{ flex: 1, gap: 4 }}>
          <T v="heading">Armed time</T>
          <T v="small" color="muted">The room was protected {fmtHours(t.armed_s)} over the last 14 days.</T>
        </View>
      </Card>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
        <Metric icon="alarm-light-outline" label="Alarms" tone={t.alarms ? 'danger' : 'neutral'} value={String(t.alarms)} sub="Siren or silent" />
        <Metric icon="alert-outline" label="False alarms" tone={falseAlarms ? 'warning' : 'neutral'} value={String(falseAlarms)} sub="Disarmed in time" />
        <Metric icon="cloud-upload-outline" label="Clips saved" tone="info" value={String(t.clips)} sub="Uploaded to the cloud" />
        <Metric icon="clock-alert-outline" label="Busiest hour" value={insights.hours.some(h => h) ? `${String(peak).padStart(2, '0')}h` : '—'} sub={insights.last_alarm ? `Last alarm ${fmtAgo(insights.last_alarm.ts, nowS)}` : 'No alarms'} />
      </View>

      <Section title="Alerts per day">
        <Card style={{ gap: 12 }}>
          <View style={{ minHeight: 20, flexDirection: 'row', justifyContent: 'space-between' }}>
            <T v="bodyStrong">{day ? fmtDate(day.date) : 'Tap a bar for details'}</T>
            {day ? <T v="small" color="muted">{day.alarms} alarm{day.alarms === 1 ? '' : 's'} · {day.triggers} trigger{day.triggers === 1 ? '' : 's'} · armed {fmtHours(day.armed_s)}</T> : null}
          </View>
          <BarChart data={data} series={series} selected={sel} onSelect={setSel} />
        </Card>
      </Section>

      <Section title="When it happens">
        <Card style={{ gap: 10 }}>
          <HourStrip values={insights.hours} color="warning" />
          <T v="caption" color="muted">Alerts by hour of day. Darker cells mean more activity.</T>
        </Card>
      </Section>

      {insights.by_sensor.length > 0 && (
        <Section title="Triggers by sensor">
          <Card><HBars color="warning" items={insights.by_sensor.map(s => ({ label: labelOf(s.sensor), value: s.count }))} /></Card>
        </Section>
      )}
    </>
  );
}

export default function Activity() {
  const nav = useNavigation();
  const route = useRoute();
  const { isDemo, refresh } = useData();
  const [tab, setTab] = useState('timeline');
  // Home can deep-link into Insights; a changed param wins over the last choice.
  const [seen, setSeen] = useState(null);
  if (route.params?.tab && route.params.tab !== seen) {
    setSeen(route.params.tab);
    setTab(route.params.tab);
  }

  return (
    <Screen title="Activity" subtitle="Everything the system saw" demo={isDemo} onDemoPress={() => nav.navigate('DataSource')} onRefresh={refresh}>
      <Segmented options={[{ value: 'timeline', label: 'Timeline', icon: 'timeline-clock-outline' }, { value: 'insights', label: 'Insights', icon: 'chart-areaspline' }]}
        value={tab} onChange={setTab} />
      {tab === 'timeline' ? <Timeline nav={nav} /> : <Insights />}
    </Screen>
  );
}
