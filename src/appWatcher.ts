// From Ally DSP: reports the running game so presets can follow it.
import { onRunningAppChanged } from "./backend";

let unregister: (() => void) | null = null;
let lastReported: string | null | undefined;

export function currentAppId(): string | null {
  try {
    const id = (globalThis as any).SteamUIStore?.MainRunningAppID;
    if (typeof id === "number" && id > 0) return String(id);
  } catch {
    /* ignore */
  }
  return null;
}

export function appName(appId: string | null): string {
  if (!appId) return "";
  try {
    const ov = (globalThis as any).appStore?.GetAppOverviewByAppID?.(parseInt(appId, 10));
    return ov?.display_name ?? appId;
  } catch {
    return appId;
  }
}

function report(appId: string | null) {
  if (appId === lastReported) return;
  lastReported = appId;
  onRunningAppChanged(appId).catch(() => undefined);
}

export function startAppWatcher(): void {
  report(currentAppId());
  try {
    const reg = (globalThis as any).SteamClient?.GameSessions?.RegisterForAppLifetimeNotifications?.(
      (e: { unAppID: number; bRunning: boolean }) => {
        if (e?.bRunning) report(String(e.unAppID));
        else setTimeout(() => report(currentAppId()), 800);
      },
    );
    unregister = reg?.unregister ? () => reg.unregister() : null;
  } catch {
    unregister = null;
  }
}

export function stopAppWatcher(): void {
  try {
    unregister?.();
  } catch {
    /* ignore */
  }
  unregister = null;
}
