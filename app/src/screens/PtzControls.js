import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { load, save } from '../theme/storage.js';
import { Button, Card, Icon, Segmented, T, tap, useFeedback } from '../ui/index.js';

const MOVE_S = 1.5;       // every press asks the Pi for a move of this length; it stops the camera by itself afterwards
const REPEAT_MS = 1100;   // while a button is held the move is renewed before it runs out
const SPEEDS = [{ value: 'slow', label: 'Slow' }, { value: 'normal', label: 'Normal' }, { value: 'fast', label: 'Fast' }];
const WHY = {
  camera_unreachable: 'The camera did not answer. Is it powered and on Wi-Fi?',
  camera_login_failed: 'The camera refused the password. Check it on the Pi.',
  no_free_slot: 'The camera has no free slot for another saved view.',
};
const why = r => WHY[r?.error] ?? 'The camera could not do that right now.';

function PadButton({ icon, label, onIn, onOut, style }) {
  const { colors } = useAppTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPressIn={onIn}
      onPressOut={onOut}
      style={({ pressed }) => [{
        width: 64, height: 64, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
        backgroundColor: pressed ? colors.primary : colors.surfaceAlt, borderWidth: 1, borderColor: colors.border,
      }, style]}>
      {({ pressed }) => <Icon name={icon} size={30} color={pressed ? 'onPrimary' : 'text'} />}
    </Pressable>
  );
}

/**
 * Direction pad for the camera. Shown only while the live view plays.
 * Hold a button to keep turning; let go and the camera stops.
 */
export default function PtzControls({ client, onNudge }) {
  const { colors, radius } = useAppTheme();
  const { toast, confirm } = useFeedback();
  const [info, setInfo] = useState(null);
  const [speed, setSpeed] = useState('normal');
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const holding = useRef({ timer: null, failed: false });

  useEffect(() => {
    let alive = true;
    (async () => {
      const remembered = await load('ptz.speed', null);
      try {
        const i = await client.ptzInfo();
        if (!alive) return;
        setInfo(i);
        setSpeed(SPEEDS.some(s => s.value === remembered) ? remembered : i.speed || 'normal');
      } catch {
        if (alive) setInfo({ supported: false, presets: [] });
      }
    })();
    return () => { alive = false; };
  }, [client]);

  const move = useCallback(async dir => {
    const r = await client.ptzMove(dir, MOVE_S, speed);
    if (!r.ok && !holding.current.failed) {
      holding.current.failed = true;      // one message per press, not one per repeat
      toast(why(r), 'danger');
    }
  }, [client, speed, toast]);

  const press = dir => {
    tap();
    holding.current.failed = false;
    clearInterval(holding.current.timer);
    move(dir);
    onNudge?.(dir);
    holding.current.timer = setInterval(() => { move(dir); onNudge?.(dir); }, REPEAT_MS);
  };
  const release = () => {
    if (!holding.current.timer) return;
    clearInterval(holding.current.timer);
    holding.current.timer = null;
    client.ptzStop();
  };
  // Leaving the live view (or the screen) while a button is down must not leave the camera turning.
  useEffect(() => () => {
    const h = holding.current;
    if (h.timer) { clearInterval(h.timer); h.timer = null; client.ptzStop(); }
  }, [client]);

  const pickSpeed = v => { setSpeed(v); save('ptz.speed', v); };

  const go = async p => {
    tap();
    const r = await client.ptzGo(p.id);
    if (r.ok) toast(`Camera turning to “${p.name}”`);
    else toast(why(r), 'danger');
  };
  const remove = async p => {
    const yes = await confirm({ title: `Delete “${p.name}”?`, message: 'The camera forgets this viewing position. It does not move.', confirmLabel: 'Delete', destructive: true });
    if (!yes) return;
    const r = await client.ptzDelete(p.id);
    if (r.ok) setInfo(i => ({ ...i, presets: i.presets.filter(x => x.id !== p.id) }));
    else toast(why(r), 'danger');
  };
  const saveView = async () => {
    const label = name.trim();
    if (!label || busy) return;
    setBusy(true);
    const r = await client.ptzSave(label);
    setBusy(false);
    if (r.ok) {
      setInfo(i => ({ ...i, presets: [...i.presets, { id: r.id, name: r.name }] }));
      setNaming(false);
      setName('');
      toast(`Saved “${r.name}”`, 'success');
    } else toast(why(r), 'danger');
  };

  if (!info || info.supported === false) return null;   // no controls for a camera the Pi cannot steer

  return (
    <Card style={{ gap: 16 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Icon name="axis-arrow" size={18} color="muted" />
        <T v="label" color="muted">Camera direction</T>
      </View>

      <View style={{ alignItems: 'center', gap: 8 }}>
        <PadButton icon="chevron-up" label="Turn camera up" onIn={() => press('up')} onOut={release} />
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <PadButton icon="chevron-left" label="Turn camera left" onIn={() => press('left')} onOut={release} />
          <PadButton icon="stop" label="Stop camera" onIn={() => { tap(); release(); client.ptzStop(); }} onOut={() => {}} />
          <PadButton icon="chevron-right" label="Turn camera right" onIn={() => press('right')} onOut={release} />
        </View>
        <PadButton icon="chevron-down" label="Turn camera down" onIn={() => press('down')} onOut={release} />
        <T v="caption" color="faint" style={{ marginTop: 2 }}>Hold a button to keep turning.</T>
      </View>

      <View style={{ gap: 8 }}>
        <T v="label" color="muted">Speed</T>
        <Segmented options={SPEEDS} value={speed} onChange={pickSpeed} />
      </View>

      <View style={{ gap: 10 }}>
        <T v="label" color="muted">Saved views</T>
        {info.presets.length > 0 ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {info.presets.map(p => (
              <Pressable key={p.id} accessibilityRole="button" accessibilityLabel={`Go to ${p.name}`}
                onPress={() => go(p)} onLongPress={() => remove(p)}
                style={({ pressed }) => ({
                  flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 9, paddingHorizontal: 14, borderRadius: radius.pill,
                  backgroundColor: pressed ? colors.surfaceAlt : colors.surface, borderWidth: 1, borderColor: colors.border,
                })}>
                {p.id === info.arm_preset ? <Icon name="shield-check-outline" size={15} color="primary" /> : null}
                <T v="smallStrong">{p.name}</T>
              </Pressable>
            ))}
          </View>
        ) : (
          <T v="small" color="muted">Turn the camera where you want it, then save the view to come back with one tap.</T>
        )}
        {info.presets.length > 0 && (
          <T v="caption" color="faint">
            Tap to go there, hold to delete.{info.arm_preset ? ' The shield marks the view used when the room is armed.' : ''}
          </T>
        )}

        {naming ? (
          <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
            <TextInput
              value={name}
              onChangeText={setName}
              placeholder="Name, e.g. Door"
              placeholderTextColor={colors.faint}
              maxLength={30}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={saveView}
              accessibilityLabel="Name of the saved view"
              style={{
                flex: 1, height: 46, paddingHorizontal: 14, borderRadius: radius.md, color: colors.text,
                backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border,
              }}
            />
            <Button label="Save" size="sm" full={false} loading={busy} disabled={!name.trim()} onPress={saveView} />
            <Button label="Cancel" size="sm" variant="outline" full={false} onPress={() => { setNaming(false); setName(''); }} />
          </View>
        ) : (
          <Button label="Save this view" icon="bookmark-plus-outline" variant="outline" onPress={() => setNaming(true)} />
        )}
      </View>
    </Card>
  );
}
