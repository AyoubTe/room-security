import { ActivityIndicator, Pressable, Text, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { tint } from '../theme/tokens.js';
import { tap } from './haptics.js';

/** Text with a type-scale variant and a colour token (or any raw colour). */
export function T({ v = 'body', color = 'text', style, children, ...rest }) {
  const { colors, type } = useAppTheme();
  return (
    <Text {...rest} style={[type[v], { color: colors[color] ?? color }, style]}>
      {children}
    </Text>
  );
}

export function Icon({ name, size = 20, color = 'text', style }) {
  const { colors } = useAppTheme();
  return <MaterialCommunityIcons name={name} size={size} color={colors[color] ?? color} style={style} />;
}

const TONES = {
  neutral: 'muted', primary: 'primary', success: 'success', warning: 'warning', danger: 'danger', info: 'info',
};

export function toneColor(colors, tone) {
  return colors[TONES[tone] ?? tone] ?? colors.muted;
}

/** The standard surface: rounded, hairline border in dark, soft shadow in light. */
export function Card({ children, style, onPress, padding = 16, tone, label }) {
  const { colors, radius, shadow, dark } = useAppTheme();
  const border = tone && tone !== 'neutral' ? tint(toneColor(colors, tone), dark ? 0.5 : 0.4) : colors.border;
  const base = [
    { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: border, padding }, shadow, style,
  ];
  if (!onPress) return <View style={base}>{children}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={() => { tap(); onPress(); }}
      style={({ pressed }) => [base, pressed && { opacity: 0.85, transform: [{ scale: 0.99 }] }]}>
      {children}
    </Pressable>
  );
}

export function Pill({ label, tone = 'neutral', icon, dot, style, solid }) {
  const { colors } = useAppTheme();
  const c = toneColor(colors, tone);
  const bg = solid ? c : tone === 'neutral' ? colors.surfaceAlt : tint(c, 0.14);
  const ink = solid ? '#fff' : c;
  return (
    <View style={[{
      flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start',
      paddingVertical: 4, paddingHorizontal: 9, borderRadius: 999, backgroundColor: bg,
    }, style]}>
      {dot && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: ink }} />}
      {icon && <Icon name={icon} size={13} color={ink} />}
      <T v="caption" color={ink} style={{ fontFamily: 'Inter_600SemiBold' }}>{label}</T>
    </View>
  );
}

export function Button({ label, icon, onPress, variant = 'primary', size = 'md', loading, disabled, style, full = true }) {
  const { colors, radius } = useAppTheme();
  const v = {
    primary: { bg: colors.primary, ink: colors.onPrimary },
    danger: { bg: colors.danger, ink: '#fff' },
    secondary: { bg: colors.surfaceAlt, ink: colors.text },
    outline: { bg: 'transparent', ink: colors.text, border: colors.border },
    ghost: { bg: 'transparent', ink: colors.primary },
  }[variant];
  const pad = size === 'lg' ? 16 : size === 'sm' ? 8 : 12;
  const off = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={off}
      onPress={() => { tap(); onPress?.(); }}
      style={({ pressed }) => [{
        flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
        paddingVertical: pad, paddingHorizontal: size === 'sm' ? 12 : 18, borderRadius: size === 'sm' ? radius.pill : radius.md,
        backgroundColor: v.bg, borderWidth: v.border ? 1 : 0, borderColor: v.border,
        alignSelf: full ? 'stretch' : 'flex-start', opacity: off ? 0.5 : pressed ? 0.8 : 1,
      }, style]}>
      {loading ? <ActivityIndicator size="small" color={v.ink} /> : icon ? <Icon name={icon} size={size === 'lg' ? 20 : 18} color={v.ink} /> : null}
      <T v={size === 'sm' ? 'smallStrong' : 'bodyStrong'} color={v.ink}>{label}</T>
    </Pressable>
  );
}

export function IconButton({ icon, onPress, size = 40, tone, label, style }) {
  const { colors } = useAppTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={() => { tap(); onPress?.(); }}
      hitSlop={6}
      style={({ pressed }) => [{
        width: size, height: size, borderRadius: size / 2, backgroundColor: colors.surfaceAlt,
        alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.6 : 1,
      }, style]}>
      <Icon name={icon} size={size * 0.5} color={tone ?? 'text'} />
    </Pressable>
  );
}

/** A round tinted icon, the visual anchor of rows and tiles. */
export function IconTile({ name, tone = 'neutral', size = 40 }) {
  const { colors, radius } = useAppTheme();
  const c = toneColor(colors, tone);
  return (
    <View style={{
      width: size, height: size, borderRadius: size > 36 ? radius.md : radius.sm,
      backgroundColor: tone === 'neutral' ? colors.surfaceAlt : tint(c, 0.14),
      alignItems: 'center', justifyContent: 'center',
    }}>
      <Icon name={name} size={size * 0.52} color={tone === 'neutral' ? 'muted' : c} />
    </View>
  );
}

export function Divider({ inset = 0 }) {
  const { colors } = useAppTheme();
  return <View style={{ height: 1, backgroundColor: colors.border, marginLeft: inset }} />;
}
