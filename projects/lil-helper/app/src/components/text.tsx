// Text in Nunito: a custom font has one file per weight, so fontWeight is turned into the matching font family.
import { Text as RNText, StyleSheet, TextProps } from "react-native";
import { font } from "@/lib/theme";

export function Text({ style, ...props }: TextProps) {
  const flat = StyleSheet.flatten(style) || {};
  const w = String(flat.fontWeight ?? "400") as keyof typeof font;
  const { fontWeight: _drop, ...rest } = flat;
  return <RNText {...props} style={[{ fontFamily: flat.fontFamily ?? font[w] ?? font["400"] }, rest]} />;
}
