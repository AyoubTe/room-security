import AsyncStorage from '@react-native-async-storage/async-storage';

/** Tiny wrapper: storage can fail (private mode, cleared data), and the app must still run. */
export async function load(key, fallback = null) {
  try {
    const v = await AsyncStorage.getItem(key);
    return v == null ? fallback : v;
  } catch {
    return fallback;
  }
}

export async function save(key, value) {
  try {
    await AsyncStorage.setItem(key, String(value));
  } catch {
    // not persisted; the choice still applies for this session
  }
}
