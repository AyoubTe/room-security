import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Image, View } from 'react-native';
import { useIsFocused } from '@react-navigation/native';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { VideoView, useVideoPlayer } from 'expo-video';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Button, Card, Group, Icon, Pill, Row, Screen, T, useFeedback } from '../ui/index.js';
import { fmtClock } from '../format.js';
import PtzControls from './PtzControls.js';

const KEEP_AWAKE = 'live-camera';
const clamp = v => Math.max(-1, Math.min(1, v));
const FRAME = { width: '100%', aspectRatio: 16 / 9, borderRadius: 16, overflow: 'hidden', backgroundColor: '#000' };

function Player({ url, headers, onFail, onReady }) {
  const player = useVideoPlayer({ uri: url, headers, contentType: 'hls' }, p => {
    p.loop = false;
    p.play();
  });
  useEffect(() => {
    const sub = player.addListener('statusChange', ({ status }) => {
      if (status === 'readyToPlay') onReady();
      if (status === 'error') onFail();
    });
    return () => sub.remove();
  }, [player, onFail, onReady]);
  return <VideoView player={player} style={{ width: '100%', height: '100%' }} contentFit="cover" nativeControls={false} />;
}

function Overlay({ live, tz }) {
  const nowS = useServerNow(1000);
  return (
    <>
      <View style={{ position: 'absolute', top: 12, left: 12, flexDirection: 'row', gap: 8 }}>
        <Pill solid tone={live ? 'danger' : 'neutral'} label={live ? 'LIVE' : 'SNAPSHOT'} dot={live} />
      </View>
      <View style={{ position: 'absolute', bottom: 10, left: 12, backgroundColor: 'rgba(0,0,0,0.55)', paddingVertical: 3, paddingHorizontal: 8, borderRadius: 6 }}>
        <T v="caption" color="#fff" style={{ fontVariant: ['tabular-nums'] }}>{fmtClock(nowS, tz)}</T>
      </View>
    </>
  );
}

export default function Camera() {
  const { colors } = useAppTheme();
  const { client, pi, isDemo } = useData();
  const { toast } = useFeedback();
  const focused = useIsFocused();
  const st = pi.status;
  const [mode, setMode] = useState('snapshot'); // snapshot | connecting | live | failed
  const [url, setUrl] = useState(null);
  const [src, setSrc] = useState(() => client.snapshotSource());
  const [attempt, setAttempt] = useState(0);
  const [pan, setPan] = useState({ x: 0, y: 0 });   // demo mode only: the sample picture shifts as if the camera turned

  // Refresh the still every few seconds while the screen is open and no video is playing.
  useEffect(() => {
    if (!focused || mode === 'live' || mode === 'connecting') return undefined;
    const id = setInterval(() => setSrc(client.snapshotSource()), 5000);
    return () => clearInterval(id);
  }, [client, focused, mode]);

  const start = useCallback(async () => {
    if (isDemo) { setMode('live'); return; }
    setMode('connecting');
    try {
      setUrl(await client.liveUrl());
      setAttempt(a => a + 1);
    } catch {
      setMode('failed');
      toast('Live view is unavailable. Is the Pi reachable?', 'danger');
    }
  }, [client, isDemo, toast]);

  const stop = () => { setMode('snapshot'); setUrl(null); setPan({ x: 0, y: 0 }); setSrc(client.snapshotSource()); };
  const onFail = useCallback(() => setMode('failed'), []);
  const onReady = useCallback(() => setMode('live'), []);
  const playing = mode === 'live' || mode === 'connecting';
  const nudge = useCallback(dir => setPan(p => ({
    x: clamp(p.x + (dir === 'right' ? 0.34 : dir === 'left' ? -0.34 : 0)),
    y: clamp(p.y + (dir === 'down' ? 0.34 : dir === 'up' ? -0.34 : 0)),
  })), []);

  // The phone must not dim or lock while someone is watching the room.
  useEffect(() => {
    if (!playing) return undefined;
    activateKeepAwakeAsync(KEEP_AWAKE).catch(() => {});
    return () => { deactivateKeepAwake(KEEP_AWAKE).catch(() => {}); };
  }, [playing]);

  return (
    <Screen bare>
      <View style={FRAME}>
        {playing && !isDemo && url ? <Player key={attempt} url={url} headers={client.liveHeaders} onFail={onFail} onReady={onReady} />
          : <Image source={src} resizeMode="cover" style={{
            width: '100%', height: '100%',
            ...(isDemo && mode === 'live' ? { transform: [{ scale: 1.5 }, { translateX: -pan.x * 40 }, { translateY: -pan.y * 24 }] } : null),
          }} />}
        {mode === 'connecting' && (
          <View style={{ ...StyleAbs, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
            <ActivityIndicator color={colors.primary} />
            <T v="small" color="#fff">Connecting to camera…</T>
          </View>
        )}
        {mode === 'failed' && (
          <View style={{ ...StyleAbs, backgroundColor: 'rgba(0,0,0,0.65)', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 24 }}>
            <Icon name="video-off-outline" size={26} color="#fff" />
            <T v="small" color="#fff" style={{ textAlign: 'center' }}>Could not play the stream. Check the Pi and the camera.</T>
          </View>
        )}
        <Overlay live={mode === 'live'} tz={st?.timezone} />
      </View>

      <View style={{ flexDirection: 'row', gap: 12 }}>
        {playing
          ? <Button label="Stop live view" icon="stop" variant="secondary" style={{ flex: 1 }} onPress={stop} />
          : <Button label={mode === 'failed' ? 'Try again' : 'Watch live'} icon="play" style={{ flex: 1 }} onPress={start} />}
        <Button label="Refresh still" icon="image-refresh" variant="outline" style={{ flex: 1 }} disabled={playing} onPress={() => setSrc(client.snapshotSource())} />
      </View>

      {mode === 'live' && <PtzControls client={client} onNudge={isDemo ? nudge : undefined} />}

      {isDemo && (
        <Card tone="info" style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}>
          <Icon name="flask-outline" color="info" />
          <T v="small" color="muted" style={{ flex: 1 }}>Demo mode shows a sample picture. With the real camera this is the live view from your Pi.</T>
        </Card>
      )}

      <Group>
        <Row icon="video-outline" tone={st?.camera_ok ? 'success' : 'danger'} title="Camera" value={st?.camera_ok ? 'Online' : 'Offline'} />
        <Row icon="record-rec" tone={st?.recording?.capturing ? 'danger' : 'neutral'} title="Recording"
          value={st?.recording?.capturing ? (st.recording.uploading ? 'Uploading clips' : 'Capturing') : 'Standing by'} />
        <Row icon="cloud-outline" tone={st?.cloud?.configured ? 'success' : 'neutral'} title="Cloud storage"
          value={st?.cloud?.configured ? (st.cloud.pending_files ? `${st.cloud.pending_files} pending` : 'Up to date') : 'Not set up'} />
      </Group>
      <T v="caption" color="faint" style={{ paddingHorizontal: 4 }}>
        The camera only streams while you watch, so the Pi stays quiet the rest of the time. During an alarm it records on its own.
      </T>
    </Screen>
  );
}

const StyleAbs = { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 };
