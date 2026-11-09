import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { Icon, T, tap } from '../ui/index.js';
import { tint } from '../theme/tokens.js';

const ICONS = {
  Home: ['view-dashboard-outline', 'view-dashboard'],
  Devices: ['cctv', 'cctv'],
  Activity: ['chart-timeline-variant', 'chart-timeline-variant'],
  Settings: ['cog-outline', 'cog'],
};

export default function TabBar({ state, navigation, badges = {} }) {
  const { colors } = useAppTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={{
      flexDirection: 'row', backgroundColor: colors.surface, borderTopWidth: 1, borderColor: colors.border,
      paddingBottom: Math.max(insets.bottom, 8), paddingTop: 8, paddingHorizontal: 8,
    }}>
      {state.routes.map((route, index) => {
        const focused = state.index === index;
        const [outline, filled] = ICONS[route.name] ?? ['circle-outline', 'circle'];
        const badge = badges[route.name];
        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            accessibilityLabel={route.name}
            onPress={() => {
              tap();
              const ev = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
              if (!focused && !ev.defaultPrevented) navigation.navigate(route.name);
            }}
            style={{ flex: 1, alignItems: 'center', gap: 3 }}>
            <View style={{
              width: 56, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center',
              backgroundColor: focused ? tint(colors.primary, 0.16) : 'transparent',
            }}>
              <Icon name={focused ? filled : outline} size={23} color={focused ? 'primary' : 'faint'} />
              {badge ? (
                <View style={{ position: 'absolute', top: 2, right: 12, width: 10, height: 10, borderRadius: 5, backgroundColor: colors.danger, borderWidth: 2, borderColor: colors.surface }} />
              ) : null}
            </View>
            <T v="caption" color={focused ? 'primary' : 'faint'} style={{ fontFamily: focused ? 'Inter_600SemiBold' : 'Inter_500Medium' }}>
              {route.name}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}
