// The Dinner Peace design system (CLAUDE.md in the brand folder): soft sage and kraft, warm canvas, charcoal ink, Nunito,
// 24px cards with a diffuse warm shadow. Never pure black or a stark white page. Pro (chef) actions are kraft.
import { Platform, StyleSheet } from "react-native";

export const c = {
  // surfaces
  bg: "#FAF7F2",          // canvas-bg
  card: "#FFFDF9",        // card-surface
  parchment: "#F4EFE6",   // grouped backgrounds, tab bars
  line: "#E8E0D5",        // border-subtle
  // text
  ink: "#2B231D",         // ink-charcoal
  muted: "#7A6F66",       // text-muted
  // brand
  sage: "#9FB8A6",        // sage-primary (icon tile, success accents)
  primary: "#476B55",     // sage-deep: primary buttons, active tabs
  primaryDark: "#2F4A39", // sage-dark: pressed, deep accents
  sageLight: "#C3D8C9",
  primarySoft: "#EBF2ED", // sage-soft: badges, selected tiles
  pro: "#8E683E",         // kraft-deep: Dinner Peace Pro buttons, chef badges
  kraft: "#CFA676",
  kraftLight: "#DFBE90",
  proSoft: "#F6EFE6",     // kraft-soft
  // food accents and states
  green: "#476B55",       // done / success
  greenSoft: "#EBF2ED",
  amber: "#8A5A12",       // warning text on cheese-melt soft
  amberSoft: "#FFF2D9",
  cheese: "#F4B53E",
  carrot: "#E26D44",      // notification dots, important tags
  red: "#D95850",         // apple-red: allergies, delete
  redSoft: "#FCE8E6",
  blush: "#FFAFAF",
  spoon: "#B8C2C7",       // disabled
  onPrimary: "#FFFDF9",
};

// Nunito by weight (loaded in app/_layout.tsx); our <Text> maps fontWeight to these.
export const font = {
  "400": "Nunito_400Regular", "500": "Nunito_600SemiBold", "600": "Nunito_600SemiBold", "700": "Nunito_700Bold",
  "800": "Nunito_800ExtraBold", "900": "Nunito_900Black", normal: "Nunito_400Regular", bold: "Nunito_700Bold",
} as const;

export const radius = 24;
export const shadow = Platform.select({
  web: { boxShadow: "0 8px 24px rgba(43, 35, 29, 0.06)" } as object,
  default: { shadowColor: "#2B231D", shadowOpacity: 0.06, shadowRadius: 12, shadowOffset: { width: 0, height: 8 },
    elevation: 2 },
});

export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: c.bg },
  pad: { padding: 16, gap: 12 },
  card: { backgroundColor: c.card, borderRadius: radius, padding: 16, borderWidth: 1, borderColor: c.line, gap: 6,
    ...shadow },
  h1: { fontSize: 24, fontWeight: "800", color: c.ink },
  h2: { fontSize: 17, fontWeight: "800", color: c.ink },
  body: { fontSize: 15, color: c.ink },
  muted: { fontSize: 13, color: c.muted },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  between: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  btn: { backgroundColor: c.primary, borderRadius: 16, paddingVertical: 13, paddingHorizontal: 18, alignItems: "center" },
  btnPro: { backgroundColor: c.pro },
  btnText: { color: c.onPrimary, fontSize: 16, fontWeight: "800" },
  ghost: { borderRadius: 14, paddingVertical: 9, paddingHorizontal: 13, borderWidth: 1, borderColor: c.line,
    backgroundColor: c.card, alignItems: "center" },
  ghostText: { color: c.ink, fontSize: 14, fontWeight: "700" },
  pill: { borderRadius: 999, paddingVertical: 3, paddingHorizontal: 10, alignSelf: "flex-start" },
  label: { fontSize: 12, fontWeight: "800", color: c.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { borderRadius: 999, borderWidth: 1, borderColor: c.line, backgroundColor: c.card, paddingVertical: 6,
    paddingHorizontal: 12 },
  chipText: { fontSize: 14, color: c.ink, fontWeight: "700" },
  step: { paddingVertical: 10, paddingHorizontal: 16 },
  input: { backgroundColor: c.card, borderWidth: 1, borderColor: c.line, borderRadius: 14, padding: 12, fontSize: 16,
    color: c.ink, fontFamily: font["400"] },
  link: { color: c.primary, fontWeight: "800" },
});
