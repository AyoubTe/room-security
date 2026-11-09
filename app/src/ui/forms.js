import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { tint } from '../theme/tokens.js';
import { Icon, T } from './primitives.js';
import { tap } from './haptics.js';
import { DAY_LETTERS, parseTime, shiftTime } from '../format.js';

/** Pill-shaped segmented control. options: [{ value, label, icon? }] */
export function Segmented({ options, value, onChange, style }) {
  const { colors, radius } = useAppTheme();
  return (
    <View style={[{ flexDirection: 'row', backgroundColor: colors.surfaceAlt, borderRadius: radius.md, padding: 3 }, style]}>
      {options.map(o => {
        const on = o.value === value;
        return (
          <Pressable
            key={String(o.value)}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            onPress={() => { tap(); onChange(o.value); }}
            style={{
              flex: 1, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center', paddingVertical: 9,
              borderRadius: radius.md - 3, backgroundColor: on ? colors.surface : 'transparent',
              borderWidth: on ? 1 : 0, borderColor: colors.border,
            }}>
            {o.icon ? <Icon name={o.icon} size={16} color={on ? 'primary' : 'muted'} /> : null}
            <T v="smallStrong" color={on ? 'text' : 'muted'}>{o.label}</T>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Wrapping chips, pick one. */
export function Choice({ options, value, onChange, disabled }) {
  const { colors, radius } = useAppTheme();
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {options.map(o => {
        const on = o.value === value;
        return (
          <Pressable
            key={String(o.value)}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            onPress={() => { tap(); onChange(o.value); }}
            style={({ pressed }) => ({
              paddingVertical: 8, paddingHorizontal: 14, borderRadius: radius.pill, borderWidth: 1,
              borderColor: on ? colors.primary : colors.border, backgroundColor: on ? tint(colors.primary, 0.14) : 'transparent',
              opacity: disabled ? 0.5 : pressed ? 0.7 : 1,
            })}>
            <T v="smallStrong" style={{ color: on ? colors.primary : colors.text }}>{o.label}</T>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Mon..Sun toggles; `value` holds weekday numbers (0 = Monday). */
export function DayPicker({ value, onChange, minOne, disabled }) {
  const { colors } = useAppTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 6 }}>
      {DAY_LETTERS.map((letter, i) => {
        const on = value.includes(i);
        return (
          <Pressable
            key={i}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            onPress={() => {
              tap();
              const next = on ? value.filter(d => d !== i) : [...value, i].sort();
              if (minOne && next.length === 0) return;
              onChange(next);
            }}
            style={({ pressed }) => ({
              width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center',
              backgroundColor: on ? colors.primary : colors.surfaceAlt, opacity: pressed ? 0.7 : 1,
            })}>
            <T v="smallStrong" style={{ color: on ? colors.onPrimary : colors.muted }}>{letter}</T>
          </Pressable>
        );
      })}
    </View>
  );
}

function Nudge({ icon, onPress, disabled }) {
  const { colors } = useAppTheme();
  return (
    <Pressable onPress={() => { tap(); onPress(); }} disabled={disabled} hitSlop={6} style={({ pressed }) => ({
      width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceAlt, alignItems: 'center', justifyContent: 'center',
      opacity: pressed || disabled ? 0.5 : 1,
    })}>
      <Icon name={icon} size={16} />
    </Pressable>
  );
}

/**
 * Type a time ("8", "830", "08:30") or nudge it by 15 minutes. Commits on blur or submit and goes
 * back to the old value if what was typed is not a time.
 */
export function TimeField({ value, onCommit, disabled }) {
  const { colors, radius, type } = useAppTheme();
  const [text, setText] = useState(value);
  const [focused, setFocused] = useState(false);
  const commit = () => {
    setFocused(false);
    const t = parseTime(text);
    if (t && t !== value) onCommit(t);
  };
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <Nudge icon="minus" disabled={disabled} onPress={() => onCommit(shiftTime(value, -15))} />
      <TextInput
        value={focused ? text : value}
        editable={!disabled}
        onFocus={() => { setText(value); setFocused(true); }}
        onChangeText={setText}
        onBlur={commit}
        onSubmitEditing={commit}
        keyboardType="numbers-and-punctuation"
        maxLength={5}
        selectTextOnFocus
        accessibilityLabel="Time"
        style={[type.metricSm, {
          width: 76, textAlign: 'center', color: colors.text, backgroundColor: colors.surfaceAlt,
          borderRadius: radius.sm, paddingVertical: 7,
        }]}
      />
      <Nudge icon="plus" disabled={disabled} onPress={() => onCommit(shiftTime(value, 15))} />
    </View>
  );
}
