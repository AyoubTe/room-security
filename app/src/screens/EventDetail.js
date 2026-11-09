import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Image, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Button, Card, EmptyState, Group, Icon, IconTile, Pill, Row, Screen, Section, T } from '../ui/index.js';
import { dayLabel, fmtClock } from '../format.js';
import { eventMeta, fmtBytes, incidentEvents, incidentSummary } from '../lib/view.js';

/** The recordings of one incident, listed by the Pi and played inside the app. */
function Recordings({ eventId, when, expected }) {
  const nav = useNavigation();
  const { colors } = useAppTheme();
  const { client, pi } = useData();
  const [state, setState] = useState({ status: 'loading', info: null });
  const days = pi.status?.retention?.days;

  const fetchClips = useCallback(async () => {
    try {
      return { status: 'ready', info: await client.eventClips(eventId) };
    } catch {
      return { status: 'error', info: null };
    }
  }, [client, eventId]);
  useEffect(() => {
    let alive = true;
    fetchClips().then(r => { if (alive) setState(r); });
    return () => { alive = false; };
  }, [fetchClips]);
  const load = () => {
    setState({ status: 'loading', info: null });
    fetchClips().then(setState);
  };

  const { status, info } = state;
  const videos = (info?.clips ?? []).filter(c => c.kind === 'video');
  const photo = (info?.clips ?? []).find(c => c.kind === 'image');
  const open = index => nav.navigate('ClipPlayer', { eventId, names: videos.map(v => v.name), index, when });

  if (status === 'loading') {
    return <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}><ActivityIndicator color={colors.primary} /><T v="small" color="muted">Looking for the recordings…</T></Card>;
  }
  if (status === 'error') {
    return (
      <Card style={{ gap: 12 }}>
        <T v="small" color="muted">Could not reach the Pi to list the recordings. Check that you are on your home Wi-Fi or connected with Tailscale.</T>
        <Button label="Try again" icon="refresh" variant="secondary" size="sm" full={false} onPress={load} />
      </Card>
    );
  }
  if (!videos.length) {
    const why = info?.recording ? 'The room is still being recorded. Clips appear here as they are saved.'
      : info?.error ? 'The Pi could not read your cloud storage just now. Try again in a moment.'
        : expected ? `No recording is left for this incident${days ? `. Recordings older than ${days} days are deleted to save space` : ''}.`
          : 'No recording was saved for this incident.';
    return (
      <Card style={{ gap: 12 }}>
        <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
          <Icon name={info?.recording ? 'record-circle-outline' : 'filmstrip-off'} color={info?.recording ? 'danger' : 'faint'} />
          <T v="small" color="muted" style={{ flex: 1 }}>{why}</T>
        </View>
        {(info?.recording || info?.error) && <Button label="Refresh" icon="refresh" variant="secondary" size="sm" full={false} onPress={load} />}
      </Card>
    );
  }
  return (
    <View style={{ gap: 12 }}>
      {photo && (
        <View style={{ width: '100%', aspectRatio: 16 / 9, borderRadius: 16, overflow: 'hidden', backgroundColor: colors.surfaceAlt }}>
          <Image source={client.clipSource(eventId, photo.name)} style={{ width: '100%', height: '100%' }} resizeMode="cover" />
        </View>
      )}
      <Button label={videos.length > 1 ? `Play all ${videos.length} clips` : 'Play the recording'} icon="play" size="lg" onPress={() => open(0)} />
      <Group>
        {videos.map((v, i) => (
          <Row key={v.name} icon="play-circle-outline" tone="primary" title={`Clip ${i + 1}`}
            subtitle={v.where === 'pi' ? 'Not uploaded yet, plays from the Pi' : undefined}
            value={fmtBytes(v.size)} chevron onPress={() => open(i)} />
        ))}
      </Group>
      <T v="caption" color="faint" style={{ paddingHorizontal: 4 }}>
        Played straight from your cloud storage through the Pi.{days ? ` Recordings are kept ${days} days.` : days === 0 ? ' Recordings are kept for ever.' : ''}
      </T>
    </View>
  );
}

export default function EventDetail({ route }) {
  const { eventId } = route.params;
  const { events, pi } = useData();
  const nowS = useServerNow(30000);
  const tz = pi.status?.timezone;
  const list = incidentEvents(events.list, eventId);

  if (!list.length) {
    return <Screen bare><Card><EmptyState icon="timeline-clock-outline" title="Incident not found" text="It may be older than the events the app keeps loaded." /></Card></Screen>;
  }
  const sum = incidentSummary(list);
  const first = list[0];
  const last = list[list.length - 1];
  const duration = Math.max(0, Math.round(last.ts - first.ts));

  return (
    <Screen bare>
      <Card tone={sum.tone} style={{ gap: 14 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
          <IconTile name={sum.icon} tone={sum.tone} size={52} />
          <View style={{ flex: 1, gap: 4 }}>
            <T v="title">{sum.title}</T>
            <T v="small" color="muted">{dayLabel(first.ts, tz, nowS)} · {fmtClock(first.ts, tz)}</T>
          </View>
        </View>
        <T v="body">{sum.sub}</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          <Pill icon="timer-outline" label={duration >= 60 ? `${Math.floor(duration / 60)} min ${duration % 60} s` : `${duration} s`} />
          {sum.silent ? <Pill tone="info" icon="volume-off" label="Silent" /> : null}
          {sum.kinds.has('siren_silenced') ? <Pill tone="info" icon="volume-off" label="Siren silenced" /> : null}
          {sum.clips ? <Pill tone="success" icon="cloud-check-outline" label={`${sum.clips.parts} clip${sum.clips.parts === 1 ? '' : 's'} saved`} /> : null}
        </View>
      </Card>

      <Section title="What happened">
        <Group>
          {list.map(e => {
            const m = eventMeta(e.kind);
            return <Row key={e.id} icon={m.icon} tone={m.tone} title={e.text} value={fmtClock(e.ts, tz)} />;
          })}
        </Group>
      </Section>

      {(sum.kinds.has('alarm') || sum.clips) && (
        <Section title="Recordings">
          <Recordings eventId={eventId} when={`${dayLabel(first.ts, tz, nowS)} · ${fmtClock(first.ts, tz)}`} expected={!!sum.clips} />
        </Section>
      )}
    </Screen>
  );
}
