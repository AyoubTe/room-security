/**
 * Design tokens. One neutral palette per mode, one brand accent (the logo's teal) and four
 * status colours. Screens never use raw hex values: they ask the theme.
 */

export const palettes = {
  light: {
    bg: '#F3F5F8',
    surface: '#FFFFFF',
    surfaceAlt: '#EDF0F4',
    border: '#E2E6EC',
    text: '#0E1621',
    muted: '#566274',
    faint: '#8C97A6',
    primary: '#0B9A89',
    onPrimary: '#FFFFFF',
    success: '#1B9B5A',
    warning: '#C97F00',
    danger: '#D63B3B',
    info: '#2D6BE0',
    overlay: 'rgba(14,22,33,0.45)',
    heroArmed: ['#E3F6EE', '#F3FBF7'],
    heroIdle: ['#E9EEF5', '#F6F8FB'],
    heroWarn: ['#FFF0D6', '#FFF8EA'],
    heroDanger: ['#FFE0E0', '#FFF1F1'],
    heroBusy: ['#DDF3F0', '#F1FAF9'],
  },
  dark: {
    bg: '#090D13',
    surface: '#111823',
    surfaceAlt: '#18212F',
    border: '#212D3E',
    text: '#EDF1F6',
    muted: '#9AA6B7',
    faint: '#66738A',
    primary: '#3FD6C0',
    onPrimary: '#05211D',
    success: '#3BD68C',
    warning: '#F3B340',
    danger: '#FF6B6B',
    info: '#6EA2FF',
    overlay: 'rgba(3,5,8,0.7)',
    heroArmed: ['#0F2B25', '#111823'],
    heroIdle: ['#172131', '#111823'],
    heroWarn: ['#33280F', '#111823'],
    heroDanger: ['#3B1618', '#111823'],
    heroBusy: ['#0E2C2B', '#111823'],
  },
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, huge: 32 };
export const radius = { sm: 8, md: 12, lg: 16, xl: 22, pill: 999 };

export const font = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semi: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
};

/** Type scale: [fontFamily, size, lineHeight, letterSpacing] */
export const type = {
  display: { fontFamily: font.bold, fontSize: 30, lineHeight: 36, letterSpacing: -0.6 },
  title: { fontFamily: font.bold, fontSize: 22, lineHeight: 28, letterSpacing: -0.3 },
  heading: { fontFamily: font.semi, fontSize: 16, lineHeight: 22, letterSpacing: -0.1 },
  body: { fontFamily: font.regular, fontSize: 15, lineHeight: 21 },
  bodyStrong: { fontFamily: font.semi, fontSize: 15, lineHeight: 21 },
  small: { fontFamily: font.regular, fontSize: 13, lineHeight: 18 },
  smallStrong: { fontFamily: font.medium, fontSize: 13, lineHeight: 18 },
  caption: { fontFamily: font.medium, fontSize: 12, lineHeight: 16 },
  label: { fontFamily: font.semi, fontSize: 11, lineHeight: 14, letterSpacing: 0.8, textTransform: 'uppercase' },
  metric: { fontFamily: font.bold, fontSize: 26, lineHeight: 30, letterSpacing: -0.5, fontVariant: ['tabular-nums'] },
  metricSm: { fontFamily: font.bold, fontSize: 20, lineHeight: 24, letterSpacing: -0.3, fontVariant: ['tabular-nums'] },
};

export function shadowFor(dark) {
  return dark
    ? {}
    : { shadowColor: '#14213A', shadowOpacity: 0.06, shadowRadius: 10, shadowOffset: { width: 0, height: 3 }, elevation: 2 };
}

/** '#RRGGBB' + 0..1 alpha -> 8-digit hex, for soft tinted backgrounds. */
export function tint(hex, alpha) {
  const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
}
