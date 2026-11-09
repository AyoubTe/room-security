import { Children, cloneElement, isValidElement } from 'react';
import { Pressable, RefreshControl, ScrollView, Switch, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { tint } from '../theme/tokens.js';
import { Card, Divider, Icon, IconTile, Pill, T, toneColor } from './primitives.js';
import { tap } from './haptics.js';

/**
 * Root of every tab: a large title, an optional right-hand slot, pull-to-refresh and a
 * demo strip when sample data is on. Pushed screens use the native header instead (`bare`).
 */
export function Screen({ title, subtitle, right, children, refreshing, onRefresh, demo, onDemoPress, bare, contentStyle }) {
  const { colors, space } = useAppTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScrollView
        contentInsetAdjustmentBehavior="never"
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={colors.primary} colors={[colors.primary]} progressBackgroundColor={colors.surface} /> : undefined}
        contentContainerStyle={[{
          paddingTop: bare ? space.sm : insets.top + space.md, paddingHorizontal: space.lg,
          // Pushed screens run edge to edge on Android: keep the last row clear of the system navigation bar.
          paddingBottom: bare ? space.huge + Math.max(insets.bottom, space.xxl) : space.huge, gap: space.lg,
        }, contentStyle]}>
        {!bare && (
          <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: space.md }}>
            <View style={{ flex: 1 }}>
              {subtitle ? <T v="caption" color="muted" style={{ marginBottom: 2 }}>{subtitle}</T> : null}
              <T v="display">{title}</T>
            </View>
            {right}
          </View>
        )}
        {demo && (
          <Pressable onPress={onDemoPress} accessibilityRole="button" style={{
            flexDirection: 'row', alignItems: 'center', gap: 8, padding: space.md, borderRadius: 12,
            backgroundColor: tint(colors.info, 0.12), borderWidth: 1, borderColor: tint(colors.info, 0.3),
          }}>
            <Icon name="flask-outline" size={16} color="info" />
            <T v="smallStrong" color="info" style={{ flex: 1 }}>Demo mode: sample data, nothing is real.</T>
            <Icon name="chevron-right" size={16} color="info" />
          </Pressable>
        )}
        {children}
      </ScrollView>
    </View>
  );
}

export function Section({ title, action, onAction, children, style }) {
  const { colors, space } = useAppTheme();
  return (
    <View style={[{ gap: space.sm }, style]}>
      {(title || action) && (
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 4 }}>
          <T v="label" color="muted">{title}</T>
          {action ? (
            <Pressable onPress={() => { tap(); onAction?.(); }} hitSlop={10}>
              <T v="smallStrong" style={{ color: colors.primary }}>{action}</T>
            </Pressable>
          ) : null}
        </View>
      )}
      {children}
    </View>
  );
}

/** A list container: one card, rows separated by inset hairlines. */
export function Group({ children, style }) {
  const items = Children.toArray(children).filter(isValidElement);
  return (
    <Card padding={0} style={[{ overflow: 'hidden' }, style]}>
      {items.map((child, i) => cloneElement(child, { divider: i > 0, key: child.key ?? i }))}
    </Card>
  );
}

export function Row({
  icon, tone = 'neutral', title, subtitle, right, value, onPress, chevron, divider, titleColor, children, style,
}) {
  const { colors, space } = useAppTheme();
  const content = (
    <>
      {divider && <Divider inset={icon ? 68 : space.lg} />}
      <View style={[{ flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 13, paddingHorizontal: space.lg }, style]}>
        {icon ? <IconTile name={icon} tone={tone} size={38} /> : null}
        <View style={{ flex: 1, gap: 2 }}>
          <T v="bodyStrong" color={titleColor ?? 'text'}>{title}</T>
          {subtitle ? <T v="small" color="muted">{subtitle}</T> : null}
          {children}
        </View>
        {value != null ? <T v="smallStrong" color="muted" style={{ maxWidth: 150, textAlign: 'right' }}>{value}</T> : null}
        {right}
        {chevron ? <Icon name="chevron-right" size={20} color="faint" /> : null}
      </View>
    </>
  );
  if (!onPress) return <View>{content}</View>;
  return (
    <Pressable onPress={() => { tap(); onPress(); }} accessibilityRole="button" accessibilityLabel={title}
      style={({ pressed }) => ({ backgroundColor: pressed ? colors.surfaceAlt : 'transparent' })}>
      {content}
    </Pressable>
  );
}

export function Toggle({ value, onChange, disabled }) {
  const { colors } = useAppTheme();
  return (
    <Switch
      value={value}
      disabled={disabled}
      onValueChange={v => { tap(); onChange(v); }}
      trackColor={{ false: colors.border, true: colors.primary }}
      thumbColor="#fff"
      ios_backgroundColor={colors.border}
    />
  );
}

/** Small KPI tile for dashboards. */
export function Metric({ icon, label, value, unit, sub, tone = 'neutral', onPress, style }) {
  const { colors } = useAppTheme();
  const c = toneColor(colors, tone);
  return (
    <Card onPress={onPress} padding={14} style={[{ flex: 1, minWidth: 140, gap: 10 }, style]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <IconTile name={icon} tone={tone} size={30} />
        <T v="caption" color="muted" style={{ flex: 1 }} numberOfLines={1}>{label}</T>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 4 }}>
        <T v="metric" style={tone !== 'neutral' ? { color: c } : undefined}>{value}</T>
        {unit ? <T v="smallStrong" color="muted">{unit}</T> : null}
      </View>
      {sub ? <T v="caption" color="muted" numberOfLines={2}>{sub}</T> : null}
    </Card>
  );
}

/** Large status card with a soft state-coloured wash. */
export function Hero({ colors: pair, tone = 'neutral', children, style }) {
  const { colors, radius, shadow, dark } = useAppTheme();
  const c = toneColor(colors, tone);
  return (
    <LinearGradient
      colors={pair}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[{
        borderRadius: radius.xl, padding: 20, borderWidth: 1, borderColor: tint(c, dark ? 0.35 : 0.3), gap: 16,
      }, shadow, style]}>
      {children}
    </LinearGradient>
  );
}

export function EmptyState({ icon = 'tray-remove', title, text, action }) {
  return (
    <View style={{ alignItems: 'center', paddingVertical: 36, paddingHorizontal: 24, gap: 10 }}>
      <IconTile name={icon} size={56} />
      <T v="heading" style={{ textAlign: 'center' }}>{title}</T>
      {text ? <T v="small" color="muted" style={{ textAlign: 'center', maxWidth: 280 }}>{text}</T> : null}
      {action}
    </View>
  );
}

export function StatusPill({ online, label }) {
  return <Pill dot tone={online ? 'success' : 'danger'} label={label ?? (online ? 'Online' : 'Offline')} />;
}
