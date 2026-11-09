import { useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, Defs, G, LinearGradient, Line, Path, Rect, Stop, Text as SvgText } from 'react-native-svg';
import { useAppTheme } from '../theme/ThemeProvider.js';
import { tint } from '../theme/tokens.js';
import { T } from '../ui/primitives.js';

function useWidth() {
  const [w, setW] = useState(0);
  return [w, e => setW(Math.round(e.nativeEvent.layout.width))];
}

const niceMax = v => {
  if (v <= 4) return 4;
  const step = v <= 10 ? 2 : v <= 20 ? 5 : 10;
  return Math.ceil(v / step) * step;
};

/**
 * Stacked bar chart. data: [{ label, values: { [seriesKey]: n } }]; series: [{ key, color, label }].
 * Tapping a bar reports its index so the caller can show details above the chart.
 */
export function BarChart({ data, series, height = 150, selected, onSelect, labelEvery = 2 }) {
  const { colors, font } = useAppTheme();
  const [w, onLayout] = useWidth();
  const padB = 22;
  const padT = 8;
  const padL = 24;
  const innerH = height - padB - padT;
  const totals = data.map(d => series.reduce((s, k) => s + (d.values[k.key] || 0), 0));
  const max = niceMax(Math.max(...totals, 1));
  const n = Math.max(1, data.length);
  const slot = w > 0 ? (w - padL) / n : 0;
  const bw = Math.max(4, Math.min(22, slot * 0.62));

  return (
    <View onLayout={onLayout} style={{ height }}>
      {w > 0 && (
        <Svg width={w} height={height}>
          {[0, 0.5, 1].map(f => {
            const y = padT + innerH * (1 - f);
            return (
              <G key={f}>
                <Line x1={padL} x2={w} y1={y} y2={y} stroke={colors.border} strokeWidth={1} strokeDasharray={f === 0 ? undefined : '3 4'} />
                <SvgText x={0} y={y + 4} fontSize={10} fontFamily={font.medium} fill={colors.faint}>{Math.round(max * f)}</SvgText>
              </G>
            );
          })}
          {data.map((d, i) => {
            const x = padL + slot * i + (slot - bw) / 2;
            let y = padT + innerH;
            const isSel = selected === i;
            const dim = selected != null && !isSel;
            return (
              <G key={d.label + i} opacity={dim ? 0.45 : 1}>
                {series.map(k => {
                  const v = d.values[k.key] || 0;
                  if (!v) return null;
                  const h = Math.max(3, (v / max) * innerH);
                  y -= h;
                  return <Rect key={k.key} x={x} y={y} width={bw} height={h} rx={Math.min(5, bw / 2)} fill={k.color} />;
                })}
                {totals[i] === 0 && <Rect x={x} y={padT + innerH - 3} width={bw} height={3} rx={1.5} fill={colors.border} />}
                {i % labelEvery === (n - 1) % labelEvery && (
                  <SvgText x={x + bw / 2} y={height - 6} fontSize={10} fontFamily={font.medium} fill={isSel ? colors.text : colors.faint} textAnchor="middle">
                    {d.label}
                  </SvgText>
                )}
                <Rect x={padL + slot * i} y={0} width={slot} height={height} fill="transparent" onPress={() => onSelect?.(isSel ? null : i)} />
              </G>
            );
          })}
        </Svg>
      )}
    </View>
  );
}

/** Smooth-ish line with a soft fill. */
export function Sparkline({ values, color = 'primary', height = 44, fill = true, strokeWidth = 2, min, max }) {
  const { colors } = useAppTheme();
  const [w, onLayout] = useWidth();
  const c = colors[color] ?? color;
  const lo = min ?? Math.min(...values);
  const hi = max ?? Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => [
    values.length === 1 ? w / 2 : (i / (values.length - 1)) * (w - 4) + 2,
    height - 4 - ((v - lo) / span) * (height - 8),
  ]);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const area = `${line} L${pts[pts.length - 1]?.[0] ?? 0} ${height} L${pts[0]?.[0] ?? 0} ${height} Z`;
  return (
    <View onLayout={onLayout} style={{ height }}>
      {w > 0 && values.length > 0 && (
        <Svg width={w} height={height}>
          <Defs>
            <LinearGradient id={`g${c.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={c} stopOpacity={0.28} />
              <Stop offset="1" stopColor={c} stopOpacity={0} />
            </LinearGradient>
          </Defs>
          {fill && <Path d={area} fill={`url(#g${c.replace("#", "")})`} />}
          <Path d={line} stroke={c} strokeWidth={strokeWidth} fill="none" strokeLinejoin="round" strokeLinecap="round" />
        </Svg>
      )}
    </View>
  );
}

/** 24 cells, one per hour; darker means busier. */
export function HourStrip({ values, color = 'primary' }) {
  const { colors, font } = useAppTheme();
  const [w, onLayout] = useWidth();
  const c = colors[color] ?? color;
  const max = Math.max(...values, 1);
  const gap = 3;
  const cw = w > 0 ? (w - gap * 23) / 24 : 0;
  return (
    <View onLayout={onLayout} style={{ height: 52 }}>
      {w > 0 && (
        <Svg width={w} height={52}>
          {values.map((v, h) => (
            <Rect key={h} x={h * (cw + gap)} y={0} width={cw} height={34} rx={4}
              fill={v === 0 ? colors.surfaceAlt : tint(c, 0.25 + 0.75 * (v / max))} />
          ))}
          {[0, 6, 12, 18].map(h => (
            <SvgText key={h} x={h * (cw + gap)} y={49} fontSize={10} fontFamily={font.medium} fill={colors.faint}>
              {String(h).padStart(2, '0')}h
            </SvgText>
          ))}
        </Svg>
      )}
    </View>
  );
}

/** Circular progress with content in the middle. */
export function Ring({ progress, size = 72, stroke = 8, color = 'primary', children }) {
  const { colors } = useAppTheme();
  const c = colors[color] ?? color;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(1, progress));
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <Svg width={size} height={size} style={{ position: 'absolute' }}>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={colors.surfaceAlt} strokeWidth={stroke} fill="none" />
        <Circle
          cx={size / 2} cy={size / 2} r={r} stroke={c} strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={`${circ * p} ${circ}`} transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </Svg>
      {children}
    </View>
  );
}

/** Four rising bars, for Zigbee link quality (0-255). */
export function SignalBars({ value }) {
  const { colors } = useAppTheme();
  const level = value == null ? 0 : value > 170 ? 4 : value > 120 ? 3 : value > 70 ? 2 : value > 20 ? 1 : 0;
  const tone = level >= 3 ? colors.success : level === 2 ? colors.warning : colors.danger;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 2, height: 14 }} accessibilityLabel={`Signal ${level} of 4`}>
      {[1, 2, 3, 4].map(i => (
        <View key={i} style={{ width: 3.5, height: 3 + i * 2.7, borderRadius: 1.5, backgroundColor: i <= level ? tone : colors.border }} />
      ))}
    </View>
  );
}

export function BatteryBar({ value }) {
  const { colors } = useAppTheme();
  if (value == null) return <T v="caption" color="faint">n/a</T>;
  const tone = value <= 20 ? colors.danger : value <= 40 ? colors.warning : colors.success;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }} accessibilityLabel={`Battery ${value} percent`}>
      <View style={{ width: 26, height: 12, borderRadius: 3, borderWidth: 1.5, borderColor: colors.faint, padding: 1.5 }}>
        <View style={{ width: `${Math.max(6, value)}%`, height: '100%', borderRadius: 1.5, backgroundColor: tone }} />
      </View>
      <T v="caption" color="muted" style={{ fontVariant: ['tabular-nums'] }}>{value}%</T>
    </View>
  );
}

/** Horizontal ranked bars: items [{ label, value }]. */
export function HBars({ items, color = 'primary' }) {
  const { colors } = useAppTheme();
  const c = colors[color] ?? color;
  const max = Math.max(...items.map(i => i.value), 1);
  return (
    <View style={{ gap: 12 }}>
      {items.map(i => (
        <View key={i.label} style={{ gap: 6 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <T v="smallStrong">{i.label}</T>
            <T v="smallStrong" color="muted" style={{ fontVariant: ['tabular-nums'] }}>{i.value}</T>
          </View>
          <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.surfaceAlt, overflow: 'hidden' }}>
            <View style={{ width: `${(i.value / max) * 100}%`, height: '100%', borderRadius: 4, backgroundColor: c }} />
          </View>
        </View>
      ))}
    </View>
  );
}
