import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useData } from '../data/DataProvider.js';
import { Button, Card, Choice, Icon, Pill, Screen, T, Toggle, useFeedback } from '../ui/index.js';

// Saved views can be numbered from 0 on some cameras, so "none" must not be 0.
const NONE = -1;

/** Which saved camera view each sensor turns the camera to when it detects an intrusion. */
export default function CameraFollow() {
  const nav = useNavigation();
  const { client, pi, settings, saveSettings } = useData();
  const { toast } = useFeedback();
  const [views, setViews] = useState(null); // saved views of the camera: [{ id, name }]
  const cam = settings?.settings.camera;
  const sensors = pi.status?.sensors ?? [];

  useEffect(() => {
    let alive = true;
    client.ptzInfo().then(i => alive && setViews(i.supported ? i.presets : [])).catch(() => alive && setViews([]));
    return () => { alive = false; };
  }, [client]);

  if (!cam) return <Screen bare><Card><T color="muted">Loading…</T></Card></Screen>;

  const save = async patch => {
    const r = await saveSettings({ camera: patch });
    if (!r.ok) toast(r.detail ?? 'Could not save.', 'danger');
  };
  const options = [{ value: NONE, label: 'Stay put' }, ...(views ?? []).map(v => ({ value: v.id, label: v.name }))];
  const known = new Set((views ?? []).map(v => v.id));

  return (
    <Screen bare>
      <Card style={{ gap: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <Icon name="cctv" color={cam.follow ? 'primary' : 'muted'} size={24} />
          <View style={{ flex: 1 }}>
            <T v="heading">Follow the intrusion</T>
            <T v="small" color="muted">When an alarm starts, the camera turns to the saved view of the sensor that detected it.</T>
          </View>
          <Toggle value={cam.follow} onChange={v => save({ follow: v })} />
        </View>
      </Card>

      {views && views.length === 0 && (
        <Card style={{ gap: 12 }}>
          <T v="small" color="muted">No saved view yet. Turn the camera towards each sensor on the Camera screen and save the view there (Saved views, then Save this view).</T>
          <Button label="Open the camera" icon="video-outline" variant="secondary" size="sm" full={false} onPress={() => nav.navigate('Camera')} />
        </Card>
      )}

      {views && views.length > 0 && sensors.map(s => {
        const chosen = cam.views[s.name];
        const missing = chosen != null && !known.has(chosen);
        return (
          <Card key={s.name} style={{ gap: 10, opacity: cam.follow ? 1 : 0.55 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <T v="bodyStrong" style={{ flex: 1 }}>{s.label}</T>
              {missing ? <Pill tone="warning" icon="alert-outline" label="View deleted" /> : null}
            </View>
            <Choice options={options} value={missing ? NONE : (chosen ?? NONE)} disabled={!cam.follow}
              onChange={v => save({ views: { [s.name]: v === NONE ? null : v } })} />
          </Card>
        );
      })}

      <Card style={{ flexDirection: 'row', gap: 10 }}>
        <Icon name="information-outline" color="faint" size={18} />
        <T v="caption" color="muted" style={{ flex: 1 }}>
          Tip: put the motion sensor on the view that looks at the middle of the room.
        </T>
      </Card>
    </Screen>
  );
}
