import { View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { BatteryBar, SignalBars } from '../charts/index.js';
import { useData, useServerNow } from '../data/DataProvider.js';
import { Card, Group, Icon, IconTile, Pill, Row, Screen, Section, StatusPill, T } from '../ui/index.js';
import { fmtAgo, fmtUptime } from '../format.js';
import { sensorView } from '../lib/view.js';

function Health({ label, value, ok = true }) {
  return (
    <View style={{ flex: 1, minWidth: 90, gap: 2 }}>
      <T v="caption" color="muted">{label}</T>
      <T v="bodyStrong" color={ok ? 'text' : 'warning'} style={{ fontVariant: ['tabular-nums'] }}>{value}</T>
    </View>
  );
}

export default function Devices() {
  const nav = useNavigation();
  const { pi, smoke, isDemo, refresh } = useData();
  const nowS = useServerNow(5000);
  const st = pi.status;
  const sensors = st?.sensors ?? [];
  const sys = st?.system;

  return (
    <Screen title="Devices" subtitle={`${sensors.length + 2} connected`} demo={isDemo} onDemoPress={() => nav.navigate('DataSource')} onRefresh={refresh}
      right={<StatusPill online={pi.online} label={pi.online ? 'Pi online' : 'Pi offline'} />}>

      <Section title="Raspberry Pi">
        <Card style={{ gap: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
            <IconTile name="raspberry-pi" tone={pi.online ? 'success' : 'neutral'} size={46} />
            <View style={{ flex: 1 }}>
              <T v="bodyStrong">Sentinel hub</T>
              <T v="small" color="muted">
                {st ? `${/^\d/.test(st.version) ? 'v' : ''}${st.version} · up ${fmtUptime(st.uptime_s)}` : 'Not reachable'}
              </T>
            </View>
          </View>
          {sys ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 14, rowGap: 12 }}>
              <Health label="CPU temp" value={`${sys.cpu_temp_c} °C`} ok={sys.cpu_temp_c < 70} />
              <Health label="Memory" value={`${sys.mem_used_pct}%`} ok={sys.mem_used_pct < 85} />
              <Health label="Disk" value={`${sys.disk_used_pct}%`} ok={sys.disk_used_pct < 85} />
              <Health label="Free space" value={`${sys.disk_free_gb} GB`} />
            </View>
          ) : null}
          {st && (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              <Pill dot tone={st.mqtt_ok ? 'success' : 'danger'} label="MQTT" />
              <Pill dot tone={st.zigbee_ok ? 'success' : 'danger'} label="Zigbee" />
              <Pill dot tone={st.camera_ok ? 'success' : 'danger'} label="Camera" />
              <Pill dot tone={st.cloud?.configured ? (st.cloud.last_error ? 'warning' : 'success') : 'neutral'} label="Cloud" />
            </View>
          )}
        </Card>
      </Section>

      <Section title="Room sensors">
        {sensors.length ? (
          <Group>
            {sensors.map(s => {
              const v = sensorView(s);
              return (
                <Row key={s.name} icon={v.icon} tone={v.tone} title={s.label}
                  subtitle={s.online === false ? 'Offline' : `Seen ${fmtAgo(s.last_seen, nowS)}`}
                  onPress={() => nav.navigate('SensorDetail', { name: s.name, title: s.label })}
                  right={
                    <View style={{ alignItems: 'flex-end', gap: 6 }}>
                      <Pill tone={v.tone} label={v.text} />
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                        <SignalBars value={s.linkquality} />
                        <BatteryBar value={s.battery} />
                      </View>
                    </View>
                  }
                  chevron />
              );
            })}
          </Group>
        ) : (
          <Card><T v="small" color="muted">No sensors reported yet.</T></Card>
        )}
      </Section>

      <Section title="Cameras">
        <Group>
          <Row icon="video-outline" tone={st?.camera_ok ? 'success' : 'neutral'} title="Room camera" subtitle={st?.recording?.capturing ? 'Recording' : 'Standing by'}
            onPress={() => nav.navigate('Camera')} chevron
            right={<Pill tone={st?.camera_ok ? 'success' : 'danger'} label={st?.camera_ok ? 'Live' : 'Down'} />} />
          <Row icon="smoke-detector-variant" tone={smoke.device?.smokeDetected ? 'danger' : smoke.online ? 'success' : 'neutral'} title="Smoke detector"
            subtitle={smoke.device ? `${smoke.device.rssi} dBm · up ${smoke.device.uptime}` : 'Not reachable'}
            onPress={() => nav.navigate('SmokeDetail')} chevron
            right={<Pill tone={smoke.device?.smokeDetected ? 'danger' : smoke.online ? 'success' : 'danger'} label={smoke.device?.smokeDetected ? 'Smoke' : smoke.online ? 'Clear' : 'Offline'} />} />
        </Group>
      </Section>

      <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center', paddingHorizontal: 4 }}>
        <Icon name="information-outline" size={14} color="faint" />
        <T v="caption" color="faint" style={{ flex: 1 }}>Signal is the Zigbee link quality. Batteries at 20% or less are flagged on Home.</T>
      </View>
    </Screen>
  );
}
