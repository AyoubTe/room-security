import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useColorScheme } from 'react-native';
import { MD3DarkTheme, MD3LightTheme } from 'react-native-paper';
import { palettes, radius, shadowFor, space, type, font } from './tokens.js';
import { load, save } from './storage.js';

const KEY = 'pref.theme';
const ThemeContext = createContext(null);

/**
 * Light / Dark / System, remembered between launches. The first launch is Dark; after that
 * whatever you pick stays picked (this used to reset to the phone's setting on every start).
 */
export function ThemeProvider({ children }) {
  const system = useColorScheme();
  const [mode, setModeState] = useState('dark');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let off = false;
    load(KEY, 'dark').then(v => {
      if (off) return;
      if (v === 'light' || v === 'dark' || v === 'system') setModeState(v);
      setReady(true);
    });
    return () => {
      off = true;
    };
  }, []);

  const setMode = useCallback(next => {
    setModeState(next);
    save(KEY, next);
  }, []);

  const scheme = mode === 'system' ? (system === 'light' ? 'light' : 'dark') : mode;
  const dark = scheme === 'dark';

  const value = useMemo(() => {
    const colors = palettes[scheme];
    const base = dark ? MD3DarkTheme : MD3LightTheme;
    const paper = {
      ...base,
      roundness: 3,
      fonts: { ...base.fonts, default: { ...base.fonts.default, fontFamily: font.regular } },
      colors: {
        ...base.colors,
        primary: colors.primary,
        onPrimary: colors.onPrimary,
        background: colors.bg,
        surface: colors.surface,
        surfaceVariant: colors.surfaceAlt,
        onSurface: colors.text,
        onSurfaceVariant: colors.muted,
        outline: colors.border,
        elevation: { ...base.colors.elevation, level3: colors.surface },
        inverseSurface: colors.text,
        inverseOnSurface: colors.bg,
        error: colors.danger,
      },
    };
    return {
      mode, setMode, ready, dark, scheme, colors, space, radius, type, font, paper,
      shadow: shadowFor(dark),
    };
  }, [mode, setMode, ready, dark, scheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useAppTheme() {
  const v = useContext(ThemeContext);
  if (!v) throw new Error('useAppTheme outside ThemeProvider');
  return v;
}
