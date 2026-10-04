import { addEventListener, removeEventListener } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { getState } from "../backend";
import type { ModuleStatus, PluginState, UpdateInfo } from "../types";

export function usePluginState() {
  const [state, setState] = useState<PluginState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setState(await getState());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onUpdate = (u: UpdateInfo) => setState((s) => (s ? { ...s, update: u } : s));
    const onModule = (m: ModuleStatus) => setState((s) => (s ? { ...s, modules: { ...s.modules, [m.id]: m } } : s));
    addEventListener<[UpdateInfo]>("update_state", onUpdate);
    addEventListener<[ModuleStatus]>("module_status", onModule);
    return () => {
      removeEventListener("update_state", onUpdate);
      removeEventListener("module_status", onModule);
    };
  }, [refresh]);

  return { state, error, refresh };
}
