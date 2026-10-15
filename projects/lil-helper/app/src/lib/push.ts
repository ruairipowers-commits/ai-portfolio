// Push notifications: ask once, register this phone's Expo push token with the server, and open the right screen
// when a notification is tapped. Pushes carry a short message and a link (lilhelper://week, …), nothing private.
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { router } from "expo-router";
import { Platform } from "react-native";
import { api } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false,
    shouldSetBadge: false }),
});

export type PushState = "on" | "denied" | "unsupported" | "off";

export async function pushState(): Promise<PushState> {
  if (Platform.OS === "web" || !Device.isDevice) return "unsupported";
  const p = await Notifications.getPermissionsAsync();
  return p.granted ? "on" : p.canAskAgain ? "off" : "denied";
}

export async function enablePush(): Promise<PushState> {
  if (Platform.OS === "web" || !Device.isDevice) return "unsupported";
  let p = await Notifications.getPermissionsAsync();
  if (!p.granted && p.canAskAgain) p = await Notifications.requestPermissionsAsync();
  if (!p.granted) return "denied";
  const projectId = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId
    ?? Constants.easConfig?.projectId;
  const { data } = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
  await api.registerDevice(data, Platform.OS);
  return "on";
}

// lilhelper://week?day=tue → the This week tab, and so on
export function openLink(url: string | undefined) {
  if (!url) return;
  const m = url.match(/^lilhelper:\/\/([a-z]*)\??(.*)$/);
  if (!m) return;
  const params = Object.fromEntries(new URLSearchParams(m[2]));
  const to = { week: "/", shopping: "/shopping", meals: "/meals", jobs: "/jobs", money: "/money",
    book: "/house/book" }[m[1]] ?? "/";
  router.push({ pathname: to as never, params });
}

export function listenForTaps(): () => void {
  if (Platform.OS === "web") return () => {};
  Notifications.getLastNotificationResponseAsync().then((r) =>
    openLink(r?.notification.request.content.data?.url as string | undefined));
  const sub = Notifications.addNotificationResponseReceivedListener((r) =>
    openLink(r.notification.request.content.data?.url as string | undefined));
  return () => sub.remove();
}
