import { useMemo } from 'react';
import { Pressable, View } from 'react-native';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { tint } from '../theme/tokens.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Card, DayPicker, Icon, Screen, Section, T, tap, useFeedback } from '../ui/index.js';
import { piDays } from '../format.js';

export default function DaysAtHome() {
  const { colors } = useAppTheme();
  const { pi, settings, saveSettings } = useData();
  const { toast } = useFeedback();
  const nowS = useServerNow(60000);
  const tz = pi.status?.timezone;
  const days = useMemo(() => piDays(tz, 14, nowS), [tz, nowS]);
  const sched = settings?.settings.schedule;
  if (!sched) return <Screen bare><Card><T color="muted">Loading…</T></Card></Screen>;

  const save = async patch => {
    const r = await saveSettings({ schedule: patch });
    if (!r.ok) toast(r.detail ?? 'Could not save.', 'danger');
  };
  const toggleDate = iso => {
    tap();
    const has = sched.skip_dates.includes(iso);
    save({ skip_dates: has ? sched.skip_dates.filter(d => d !== iso) : [...sched.skip_dates, iso].sort() });
  };

  return (
    <Screen bare>
      <Card style={{ flexDirection: 'row', gap: 12 }}>
        <Icon name="home-variant-outline" color="info" />
        <T v="small" color="muted" style={{ flex: 1 }}>On a day at home the schedule does not arm the room. You can still arm it by hand whenever you like.</T>
      </Card>

      <Section title="Every week">
        <Card style={{ gap: 12 }}>
          <T v="small" color="muted">Days you usually work from home or stay in.</T>
          <DayPicker value={sched.home_weekdays} onChange={d => save({ home_weekdays: d })} />
        </Card>
      </Section>

      <Section title="One-off days (next 14 days)">
        <Card style={{ gap: 12 }}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {days.map(d => {
              const weekly = sched.home_weekdays.includes(d.wd);
              const on = sched.skip_dates.includes(d.iso);
              return (
                <Pressable key={d.iso} disabled={weekly} onPress={() => toggleDate(d.iso)} accessibilityRole="button" accessibilityState={{ selected: on || weekly }}
                  style={{
                    width: '12.4%', minWidth: 42, alignItems: 'center', gap: 2, paddingVertical: 8, borderRadius: 12, borderWidth: 1,
                    borderColor: on ? colors.info : colors.border, backgroundColor: on ? tint(colors.info, 0.16) : weekly ? colors.surfaceAlt : 'transparent',
                    opacity: weekly ? 0.55 : 1,
                  }}>
                  <T v="caption" color={on ? 'info' : 'muted'}>{d.label[0]}</T>
                  <T v="bodyStrong" color={on ? 'info' : 'text'} style={{ fontVariant: ['tabular-nums'] }}>{d.num}</T>
                  <Icon name={on || weekly ? 'home-variant' : 'minus'} size={13} color={on ? 'info' : 'faint'} />
                </Pressable>
              );
            })}
          </View>
          <T v="caption" color="faint">Tap a day to mark it as a day at home. Greyed days are already weekly days at home.</T>
        </Card>
      </Section>
    </Screen>
  );
}
