import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { VideoView, useVideoPlayer } from 'expo-video';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { useData } from '../data/DataProvider.js';
import { Button, Card, Icon, Screen, T } from '../ui/index.js';

const FRAME = { width: '100%', aspectRatio: 16 / 9, borderRadius: 16, overflow: 'hidden', backgroundColor: '#000' };

/** One clip. Re-created (key) for every clip so a new file always gets a fresh player. */
function Clip({ source, onEnd }) {
  const { colors } = useAppTheme();
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const player = useVideoPlayer(source, p => {
    p.loop = false;
    p.play();
  });

  useEffect(() => {
    const a = player.addListener('statusChange', ({ status: s }) => {
      if (s === 'readyToPlay') setStatus('ready');
      if (s === 'error') setStatus('error');
    });
    const b = player.addListener('playToEnd', onEnd);
    return () => { a.remove(); b.remove(); };
  }, [player, onEnd]);

  return (
    <View style={FRAME}>
      <VideoView player={player} style={{ width: '100%', height: '100%' }} contentFit="contain" nativeControls />
      {status === 'loading' && (
        <View style={{ position: 'absolute', inset: 0, alignItems: 'center', justifyContent: 'center', gap: 8 }} pointerEvents="none">
          <ActivityIndicator color={colors.primary} />
          <T v="caption" color="#fff">Loading from your cloud storage…</T>
        </View>
      )}
      {status === 'error' && (
        <View style={{ position: 'absolute', inset: 0, alignItems: 'center', justifyContent: 'center', gap: 8, padding: 24, backgroundColor: 'rgba(0,0,0,0.7)' }}>
          <Icon name="cloud-alert" size={28} color="warning" />
          <T v="small" color="#fff" style={{ textAlign: 'center' }}>
            This clip could not be played. The Pi may be offline, or the recording was already cleaned up.
          </T>
        </View>
      )}
    </View>
  );
}

export default function ClipPlayer({ route }) {
  const { eventId, names, index = 0, when } = route.params;
  const { client } = useData();
  const [i, setI] = useState(index);
  const name = names[i];
  const many = names.length > 1;
  const next = () => setI(n => (n + 1 < names.length ? n + 1 : n));

  return (
    <Screen bare>
      <Clip key={name} source={client.clipSource(eventId, name)} onEnd={next} />
      <Card style={{ gap: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <Icon name="filmstrip" color="primary" />
          <View style={{ flex: 1 }}>
            <T v="bodyStrong">{many ? `Clip ${i + 1} of ${names.length}` : 'Recording'}</T>
            {when ? <T v="small" color="muted">{when}</T> : null}
          </View>
        </View>
        {many && (
          <View style={{ flexDirection: 'row', gap: 10 }}>
            <Button label="Previous" icon="skip-previous" variant="secondary" size="sm" full={false} disabled={i === 0} onPress={() => setI(n => Math.max(0, n - 1))} />
            <Button label="Next" icon="skip-next" variant="secondary" size="sm" full={false} disabled={i === names.length - 1} onPress={next} />
          </View>
        )}
        <T v="caption" color="muted">
          Clips play one after the other. They stream through your Pi, so you do not need to open Google Drive.
        </T>
      </Card>
    </Screen>
  );
}
