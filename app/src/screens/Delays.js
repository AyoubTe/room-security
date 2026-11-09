import { View } from 'react-native';
import { useData } from '../data/DataProvider.js';
import { Button, Card, Icon, IconButton, Screen, T, useFeedback } from '../ui/index.js';

function Stepper({ label, help, value, min, max, step, onChange }) {
  return (
    <Card style={{ gap: 12 }}>
      <View>
        <T v="heading">{label}</T>
        <T v="small" color="muted">{help}</T>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 22 }}>
        <IconButton icon="minus" size={46} label={`Less ${label}`} onPress={() => onChange(Math.max(min, value - step))} />
        <View style={{ alignItems: 'center', minWidth: 90 }}>
          <T v="display" style={{ fontVariant: ['tabular-nums'] }}>{value}</T>
          <T v="caption" color="muted">seconds</T>
        </View>
        <IconButton icon="plus" size={46} label={`More ${label}`} onPress={() => onChange(Math.min(max, value + step))} />
      </View>
    </Card>
  );
}

export default function Delays() {
  const { settings, saveSettings } = useData();
  const { toast } = useFeedback();
  const eff = settings?.effective;
  if (!eff) return <Screen bare><Card><T color="muted">Loading…</T></Card></Screen>;

  const save = async patch => {
    const r = await saveSettings({ timing: patch });
    if (!r.ok) toast(r.detail ?? 'Could not save.', 'danger');
  };

  return (
    <Screen bare>
      <Stepper label="Exit delay" help="Time to leave the room after pressing Arm." value={eff.exit_delay_s} min={5} max={300} step={5}
        onChange={v => save({ exit_delay_s: v })} />
      <Stepper label="Entry delay" help="Time to disarm after the door opens, before the alarm sounds." value={eff.entry_delay_s} min={5} max={300} step={5}
        onChange={v => save({ entry_delay_s: v })} />
      <Card style={{ flexDirection: 'row', gap: 10 }}>
        <Icon name="information-outline" color="faint" size={18} />
        <T v="caption" color="muted" style={{ flex: 1 }}>Only the door and motion sensors use the entry delay. A window opening goes straight to the alarm.</T>
      </Card>
      <Button label="Use defaults from the Pi" variant="ghost" onPress={() => save({ exit_delay_s: null, entry_delay_s: null })} />
    </Screen>
  );
}
