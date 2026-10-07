// Colours from the logo: warm cream background, apple red for actions, leaf green for "done".
import { StyleSheet } from "react-native";

export const c = {
  bg: "#FFF8EC",
  card: "#FFFFFF",
  ink: "#3A2A1E",
  muted: "#7A6A5C",
  line: "#F0E2CC",
  red: "#D7392A",
  redSoft: "#FDE7E3",
  green: "#3E9E3A",
  greenSoft: "#E6F4E1",
  amber: "#B7791F",
  amberSoft: "#FFF3D6",
};

export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: c.bg },
  pad: { padding: 16, gap: 12 },
  card: { backgroundColor: c.card, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: c.line, gap: 6 },
  h1: { fontSize: 24, fontWeight: "700", color: c.ink },
  h2: { fontSize: 17, fontWeight: "700", color: c.ink },
  body: { fontSize: 15, color: c.ink },
  muted: { fontSize: 13, color: c.muted },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  between: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  btn: { backgroundColor: c.red, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center" },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "700" },
  ghost: { borderRadius: 10, paddingVertical: 8, paddingHorizontal: 12, borderWidth: 1, borderColor: c.line,
    backgroundColor: c.card, alignItems: "center" },
  ghostText: { color: c.ink, fontSize: 14, fontWeight: "600" },
  pill: { borderRadius: 999, paddingVertical: 3, paddingHorizontal: 10, alignSelf: "flex-start" },
  input: { backgroundColor: c.card, borderWidth: 1, borderColor: c.line, borderRadius: 12, padding: 12, fontSize: 16,
    color: c.ink },
});
