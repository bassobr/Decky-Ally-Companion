import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { getState, moduleAction, setModuleEnabled, setModuleOptions } from "./backend";
import type { ModuleResult, ModuleStatus, PluginState, UpdateInfo } from "./types";

/** Plugin state shared by the panel, the fullscreen view and the Steam-side patches. */
let cache: PluginState | null = null;
let error: string | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

export const store = {
  get: () => cache,
  error: () => error,
  async refresh(): Promise<void> {
    try {
      cache = await getState();
      error = null;
    } catch (e) {
      error = String(e);
    }
    notify();
  },
  patchModule(m: ModuleStatus) {
    if (!cache) return;
    cache = { ...cache, modules: { ...cache.modules, [m.id]: m } };
    notify();
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
};

const onModule = (m: ModuleStatus) => store.patchModule(m);
const onModules = (all: Record<string, ModuleStatus>) => {
  if (!cache) return;
  cache = { ...cache, modules: all };
  notify();
};
const onUpdate = (u: UpdateInfo) => {
  if (!cache) return;
  cache = { ...cache, update: u };
  notify();
};

export function connectEvents(): void {
  addEventListener<[ModuleStatus]>("module_status", onModule);
  addEventListener<[Record<string, ModuleStatus>]>("modules", onModules);
  addEventListener<[UpdateInfo]>("update_state", onUpdate);
  void store.refresh();
}

export function disconnectEvents(): void {
  removeEventListener("module_status", onModule);
  removeEventListener("modules", onModules);
  removeEventListener("update_state", onUpdate);
}

export function usePluginState() {
  const [, setTick] = useState(0);
  useEffect(() => store.subscribe(() => setTick((t) => t + 1)), []);
  return { state: cache, error, refresh: store.refresh };
}

export function useModule(id: string): ModuleStatus | undefined {
  return usePluginState().state?.modules[id];
}

function handle(r: ModuleResult): ModuleResult {
  store.patchModule(r.status);
  if (!r.ok && r.error) toaster.toast({ title: r.status.title, body: r.error });
  return r;
}

export const mod = {
  enable: async (id: string, on: boolean) => handle(await setModuleEnabled(id, on)),
  options: async (id: string, options: Record<string, unknown>) => handle(await setModuleOptions(id, options)),
  action: async (id: string, action: string, args?: Record<string, unknown>) => handle(await moduleAction(id, action, args)),
};
