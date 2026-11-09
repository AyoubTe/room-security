import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { Button as PaperButton, Dialog, Portal, Snackbar, Text as PaperText } from 'react-native-paper';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { toneColor } from './primitives.js';
import { success, warning } from './haptics.js';

const FeedbackContext = createContext(null);

/** Toasts (Snackbar) and confirmation dialogs, as promises: `if (await confirm({...})) ...` */
export function FeedbackProvider({ children }) {
  const { colors, font } = useAppTheme();
  const [toastState, setToast] = useState(null);
  const [dialog, setDialog] = useState(null);

  const toast = useCallback((message, tone = 'neutral') => {
    if (tone === 'success') success();
    if (tone === 'danger' || tone === 'warning') warning();
    setToast({ message, tone, key: Date.now() });
  }, []);

  const confirm = useCallback(
    opts => new Promise(resolve => setDialog({ ...opts, resolve })),
    []
  );

  const close = answer => {
    dialog?.resolve(answer);
    setDialog(null);
  };

  const value = useMemo(() => ({ toast, confirm }), [toast, confirm]);
  const accent = toastState ? toneColor(colors, toastState.tone) : colors.text;

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <Portal>
        <Snackbar
          key={toastState?.key}
          visible={!!toastState}
          onDismiss={() => setToast(null)}
          duration={3500}
          style={{ backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginBottom: 90 }}
          theme={{ colors: { inverseOnSurface: colors.text, inversePrimary: colors.primary } }}>
          <PaperText style={{ color: toastState?.tone && toastState.tone !== 'neutral' ? accent : colors.text, fontFamily: font.medium }}>
            {toastState?.message}
          </PaperText>
        </Snackbar>
        <Dialog visible={!!dialog} onDismiss={() => close(false)} style={{ backgroundColor: colors.surface, borderRadius: 20 }}>
          <Dialog.Title style={{ color: colors.text, fontFamily: font.semi }}>{dialog?.title}</Dialog.Title>
          <Dialog.Content>
            <PaperText style={{ color: colors.muted, fontFamily: font.regular }}>{dialog?.message}</PaperText>
          </Dialog.Content>
          <Dialog.Actions>
            <PaperButton textColor={colors.muted} onPress={() => close(false)}>{dialog?.cancelLabel ?? 'Cancel'}</PaperButton>
            <PaperButton textColor={dialog?.destructive ? colors.danger : colors.primary} onPress={() => close(true)}>
              {dialog?.confirmLabel ?? 'OK'}
            </PaperButton>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </FeedbackContext.Provider>
  );
}

export function useFeedback() {
  const v = useContext(FeedbackContext);
  if (!v) throw new Error('useFeedback outside FeedbackProvider');
  return v;
}
