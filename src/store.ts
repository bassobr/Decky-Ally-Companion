import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { openPage } from "./navigation";
import { useEffect, useState } from "react";
import { getState, moduleAction, setModuleEnabled, setModuleOptions } from "./backend";
import type { AudioDetails, ConvertEvent, ModuleDetails, ModuleId, ModuleResult, ModuleStatus, ModuleStatuses, PluginState, SetupEvent,
  UpdateInfo } from "./types";

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
    cache = { ...cache, modules: { ...cache.modules, [m.id]: m } as ModuleStatuses };
    notify();
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
};

const onModule = (m: ModuleStatus) => store.patchModule(m);
const onModules = (all: ModuleStatuses) => {
  if (!cache) return;
  cache = { ...cache, modules: all };
  notify();
};
type AudioProgress = ({ kind: "setup" } & SetupEvent) | ({ kind: "convert" } & ConvertEvent);

/** Setup and reconversion progress of the audio module, merged into its details. */
const onAudioProgress = (ev: AudioProgress) => {
  const m = cache?.modules.audio;
  if (!m) return;
  const setup = { ...(m.details.setup ?? {}) } as AudioDetails["setup"];
  let finished: boolean;
  if (ev.kind === "setup") {
    const { kind: _kind, ...rest } = ev;
    finished = rest.step === "finished"; // setup steps report done/skipped on the way
    setup.last = rest;
    setup.inProgress = !finished;
  } else {
    const { kind: _kind, ...rest } = ev;
    finished = rest.status !== "running";
    setup.convertLast = rest;
    setup.converting = !finished;
  }
  store.patchModule({ ...m, details: { ...m.details, setup } });
  if (finished) void store.refresh();
};

/** New SteamOS releases, BIOS versions and known issues arrive once each as a toast. */
const NEWS_KIND: Record<string, string> = { steamos: "SteamOS", bios: "BIOS", firmware: "Firmware", issue: "Known issue" };
const onNews = (items: { id: string; kind: string; title: string; version?: string }[]) => {
  for (const it of items.slice(0, 3)) {
    toaster.toast({ title: `Ally Companion: ${NEWS_KIND[it.kind] ?? "News"}`, body: it.title, onClick: () => openPage("news") });
  }
  void store.refresh();
};

const onUpdate = (u: UpdateInfo) => {
  if (!cache) return;
  cache = { ...cache, update: u };
  notify();
};

export function connectEvents(): void {
  addEventListener<[ModuleStatus]>("module_status", onModule);
  addEventListener<[ModuleStatuses]>("modules", onModules);
  addEventListener<[UpdateInfo]>("update_state", onUpdate);
  addEventListener<[AudioProgress]>("audio_progress", onAudioProgress);
  addEventListener<[any]>("news_new", onNews);
  void store.refresh();
}

export function disconnectEvents(): void {
  removeEventListener("module_status", onModule);
  removeEventListener("modules", onModules);
  removeEventListener("update_state", onUpdate);
  removeEventListener("audio_progress", onAudioProgress);
  removeEventListener("news_new", onNews);
}

export function usePluginState() {
  const [, setTick] = useState(0);
  useEffect(() => store.subscribe(() => setTick((t) => t + 1)), []);
  return { state: cache, error, refresh: store.refresh };
}

export function useModule<K extends ModuleId>(id: K): ModuleStatus<ModuleDetails[K]> | undefined {
  return usePluginState().state?.modules[id] as ModuleStatus<ModuleDetails[K]> | undefined;
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
