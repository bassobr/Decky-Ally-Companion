import { callable } from "@decky/api";
import type { ModuleResult, PluginState, UpdateArtifact, UpdateInfo } from "./types";

export const getState = callable<[], PluginState>("get_state");
export const checkForUpdate = callable<[force: boolean], UpdateInfo>("check_for_update");
export const prepareUpdate = callable<[], UpdateArtifact>("prepare_update");
export const getDiagnostics = callable<[], { text: string }>("get_diagnostics");
export const setModuleEnabled = callable<[id: string, enabled: boolean], ModuleResult>("set_module_enabled");
export const setModuleOptions = callable<[id: string, options: Record<string, unknown>], ModuleResult>("set_module_options");
export const moduleAction = callable<[id: string, action: string, args?: Record<string, unknown>], ModuleResult>("module_action");
export const onRunningAppChanged = callable<[appId: string | null], { appId: string | null }>("on_running_app_changed");
export const restartSteamService = callable<[], { ok: boolean; error: string }>("restart_steam");

/** Verify the latest release in the backend, then hand it to Decky Loader's installer. */
export async function installUpdate(): Promise<void> {
  const a = await prepareUpdate();
  const backend = window.DeckyBackend;
  if (!backend?.callable) throw new Error("Decky install API not available");
  const install = backend.callable<[string, string, string, string, number], void>("utilities/install_plugin");
  // InstallType.UPDATE = 2 (decky-loader frontend enum)
  await install(a.artifact, a.name, a.version, a.hash, 2);
}
