import { DarkTheme, DefaultTheme, NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { useData } from '../data/DataProvider.js';
import TabBar from './TabBar.js';
import Home from '../screens/Home.js';
import Devices from '../screens/Devices.js';
import Activity from '../screens/Activity.js';
import Settings from '../screens/Settings.js';
import Camera from '../screens/Camera.js';
import SensorDetail from '../screens/SensorDetail.js';
import SmokeDetail from '../screens/SmokeDetail.js';
import EventDetail from '../screens/EventDetail.js';
import Schedule from '../screens/Schedule.js';
import DaysAtHome from '../screens/DaysAtHome.js';
import SirenSettings from '../screens/SirenSettings.js';
import Delays from '../screens/Delays.js';
import DataSource from '../screens/DataSource.js';
import ClipPlayer from '../screens/ClipPlayer.js';
import CameraFollow from '../screens/CameraFollow.js';
import Storage from '../screens/Storage.js';

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function Tabs() {
  const { pi } = useData();
  const hot = pi.status?.state === 'alarm' || pi.status?.state === 'entry_delay';
  return (
    <Tab.Navigator
      screenOptions={{ headerShown: false }}
      tabBar={props => <TabBar {...props} badges={{ Home: hot }} />}>
      <Tab.Screen name="Home" component={Home} />
      <Tab.Screen name="Devices" component={Devices} />
      <Tab.Screen name="Activity" component={Activity} />
      <Tab.Screen name="Settings" component={Settings} />
    </Tab.Navigator>
  );
}

export default function Navigation() {
  const { colors, dark, font } = useAppTheme();
  const base = dark ? DarkTheme : DefaultTheme;
  const theme = {
    ...base,
    colors: { ...base.colors, background: colors.bg, card: colors.bg, text: colors.text, border: colors.border, primary: colors.primary },
    fonts: base.fonts,
  };
  return (
    <NavigationContainer theme={theme}>
      <Stack.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: colors.bg },
          headerTintColor: colors.text,
          headerShadowVisible: false,
          headerTitleStyle: { fontFamily: font.semi, fontSize: 17 },
          headerBackButtonDisplayMode: 'minimal',
          contentStyle: { backgroundColor: colors.bg },
        }}>
        <Stack.Screen name="Tabs" component={Tabs} options={{ headerShown: false }} />
        <Stack.Screen name="Camera" component={Camera} options={{ title: 'Camera', presentation: 'modal' }} />
        <Stack.Screen name="SensorDetail" component={SensorDetail} options={({ route }) => ({ title: route.params?.title ?? 'Sensor' })} />
        <Stack.Screen name="SmokeDetail" component={SmokeDetail} options={{ title: 'Smoke detector' }} />
        <Stack.Screen name="EventDetail" component={EventDetail} options={{ title: 'Incident' }} />
        <Stack.Screen name="ClipPlayer" component={ClipPlayer} options={{ title: 'Recording' }} />
        <Stack.Screen name="CameraFollow" component={CameraFollow} options={{ title: 'Camera follows' }} />
        <Stack.Screen name="Storage" component={Storage} options={{ title: 'Recordings & storage' }} />
        <Stack.Screen name="Schedule" component={Schedule} options={{ title: 'Schedule' }} />
        <Stack.Screen name="DaysAtHome" component={DaysAtHome} options={{ title: 'Days at home' }} />
        <Stack.Screen name="SirenSettings" component={SirenSettings} options={{ title: 'Siren' }} />
        <Stack.Screen name="Delays" component={Delays} options={{ title: 'Delays' }} />
        <Stack.Screen name="DataSource" component={DataSource} options={{ title: 'Data source' }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
