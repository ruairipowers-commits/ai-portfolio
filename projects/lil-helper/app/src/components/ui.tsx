import { router } from "expo-router";
import React, { ReactNode, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { c, s } from "@/lib/theme";

export function Screen({ children, refreshing, onRefresh }: { children: ReactNode; refreshing?: boolean;
  onRefresh?: () => void }) {
  return (
    <SafeAreaView style={s.screen} edges={["top"]}>
      <ScrollView contentContainerStyle={s.pad}
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined}>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Button({ title, onPress, disabled, busy, kind = "primary" }: { title: string; onPress: () => void;
  disabled?: boolean; busy?: boolean; kind?: "primary" | "ghost" }) {
  const primary = kind === "primary";
  return (
    <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled || busy}
      style={({ pressed }) => [primary ? s.btn : s.ghost, { opacity: disabled ? 0.45 : pressed ? 0.8 : 1 }]}>
      {busy ? <ActivityIndicator color={primary ? "#fff" : c.ink} />
        : <Text style={primary ? s.btnText : s.ghostText}>{title}</Text>}
    </Pressable>
  );
}

export function Pill({ text, tone = "green" }: { text: string; tone?: "green" | "red" | "amber" }) {
  const bg = tone === "green" ? c.greenSoft : tone === "red" ? c.redSoft : c.amberSoft;
  const fg = tone === "green" ? c.green : tone === "red" ? c.red : c.amber;
  return <View style={[s.pill, { backgroundColor: bg }]}><Text style={{ color: fg, fontSize: 12, fontWeight: "700" }}>{text}</Text></View>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <View style={[s.card, { backgroundColor: c.redSoft, borderColor: c.redSoft }]}>
    <Text style={[s.body, { color: c.red }]}>{error instanceof Error ? error.message : String(error)}</Text>
  </View>;
}

export const money = (n: number | null | undefined) => (n == null ? "—" : `$${n.toFixed(2)}`);

// ---- form pieces used by the settings screens and the welcome wizard
export function Field({ label, hint, ...props }: { label: string; hint?: string } &
  React.ComponentProps<typeof TextInput>) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput style={s.input} placeholderTextColor={c.muted} {...props} />
      {hint ? <Text style={s.muted}>{hint}</Text> : null}
    </View>
  );
}

export function NumberField({ label, value, onChange, hint, step = 1, min = 0, max = 100000, prefix }: {
  label: string; value: number | undefined; onChange: (n: number) => void; hint?: string; step?: number;
  min?: number; max?: number; prefix?: string }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => { setText(value == null ? "" : String(value)); }, [value]);
  const clamp = (n: number) => Math.max(min, Math.min(max, Math.round(n * 100) / 100));
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <View style={s.row}>
        <Pressable accessibilityLabel={`less ${label}`} style={[s.ghost, s.step]}
          onPress={() => onChange(clamp((value ?? 0) - step))}><Text style={s.ghostText}>−</Text></Pressable>
        <View style={[s.row, { flex: 1 }]}>
          {prefix ? <Text style={s.body}>{prefix}</Text> : null}
          <TextInput style={[s.input, { flex: 1, textAlign: "center" }]} keyboardType="decimal-pad" value={text}
            onChangeText={setText} onEndEditing={() => { const n = parseFloat(text); if (!isNaN(n)) onChange(clamp(n)); }}
            onBlur={() => { const n = parseFloat(text); if (!isNaN(n)) onChange(clamp(n)); }} />
        </View>
        <Pressable accessibilityLabel={`more ${label}`} style={[s.ghost, s.step]}
          onPress={() => onChange(clamp((value ?? 0) + step))}><Text style={s.ghostText}>+</Text></Pressable>
      </View>
      {hint ? <Text style={s.muted}>{hint}</Text> : null}
    </View>
  );
}

export function Chips({ options, value, onChange, multi = true, label }: {
  options: { id: string; label: string }[] | string[]; value: string[] | string | null | undefined;
  onChange: (v: string[]) => void; multi?: boolean; label?: string }) {
  const opts = (options as (string | { id: string; label: string })[]).map((o) =>
    typeof o === "string" ? { id: o, label: o.replace(/_/g, " ") } : o);
  const sel = Array.isArray(value) ? value : value ? [value] : [];
  return (
    <View style={{ gap: 4 }}>
      {label ? <Text style={s.label}>{label}</Text> : null}
      <View style={s.wrap}>
        {opts.map((o) => {
          const on = sel.includes(o.id);
          return (
            <Pressable key={o.id} accessibilityRole={multi ? "checkbox" : "radio"} accessibilityState={{ checked: on }}
              onPress={() => onChange(multi ? (on ? sel.filter((x) => x !== o.id) : [...sel, o.id]) : [o.id])}
              style={[s.chip, on && { backgroundColor: c.greenSoft, borderColor: c.green }]}>
              <Text style={[s.chipText, on && { color: c.green }]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export function Toggle({ label, value, onChange, hint }: { label: string; value: boolean; onChange: (v: boolean) => void;
  hint?: string }) {
  return (
    <View style={[s.between, { paddingVertical: 2 }]}>
      <View style={{ flex: 1 }}>
        <Text style={s.body}>{label}</Text>
        {hint ? <Text style={s.muted}>{hint}</Text> : null}
      </View>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: c.green, false: c.line }} />
    </View>
  );
}

export function LinkRow({ icon, title, sub, onPress }: { icon: string; title: string; sub?: string;
  onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress}
      style={({ pressed }) => [s.between, { paddingVertical: 10, opacity: pressed ? 0.6 : 1 }]}>
      <Text style={{ fontSize: 20, width: 30 }}>{icon}</Text>
      <View style={{ flex: 1 }}>
        <Text style={s.body}>{title}</Text>
        {sub ? <Text style={s.muted} numberOfLines={2}>{sub}</Text> : null}
      </View>
      <Text style={[s.muted, { fontSize: 18 }]}>›</Text>
    </Pressable>
  );
}

export function Header({ title, back = true, right }: { title: string; back?: boolean; right?: ReactNode }) {
  return (
    <View style={s.between}>
      {back ? <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={() =>
        router.canGoBack() ? router.back() : router.replace("/settings")} style={{ paddingRight: 8 }}>
        <Text style={[s.h2, { color: c.red }]}>‹ Back</Text></Pressable> : null}
      <Text style={[s.h1, { flex: 1, textAlign: back ? "center" : "left" }]} numberOfLines={1}>{title}</Text>
      {right ?? (back ? <View style={{ width: 56 }} /> : null)}
    </View>
  );
}

export function Saved({ at }: { at: number | null }) {
  if (!at) return null;
  return <Text style={[s.muted, { color: c.green, textAlign: "center" }]}>Saved ✓</Text>;
}

export function AdminNote({ role }: { role?: string | null }) {
  if (!role || role === "admin") return null;
  return <View style={[s.card, { backgroundColor: c.amberSoft }]}>
    <Text style={s.body}>Only the household's admin can change these settings. You can see them, and ask.</Text></View>;
}
