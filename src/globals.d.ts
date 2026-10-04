// Decky's backend router and plugin loader; SteamClient, appStore and SteamUIStore come from @decky/ui.
interface Window {
  DeckyBackend?: { callable: <T extends any[] = any[], R = any>(route: string) => (...args: T) => Promise<R> };
  // deckyState is private in Decky's sources; present at runtime (v3.2.9).
  DeckyPluginLoader?: { deckyState?: { setActivePlugin?: (name: string) => void } };
}
