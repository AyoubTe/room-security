import * as Haptics from 'expo-haptics';

const safe = fn => {
  try {
    fn();
  } catch {
    // not available on this device (e.g. web): silently skip
  }
};

export const tap = () => safe(() => Haptics.selectionAsync());
export const success = () => safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success));
export const warning = () => safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning));
