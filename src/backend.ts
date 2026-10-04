import { callable } from "@decky/api";
import type { LiveValues, ModuleResult, PluginState, UpdateArtifact, UpdateInfo } from "./types";

export const getState = callable<[], PluginState>("get_state");
export const checkForUpdate = callable<[force: boolean], UpdateInfo>("check_for_update");
export const prepareUpdate = callable<[], UpdateArtifact>("prepare_update");
export const getDiagnostics = callable<[], { text: string }>("get_diagnostics");
export const setModuleEnabled = callable<[id: string, enabled: boolean], ModuleResult>("set_module_enabled");
export const setModuleOptions = callable<[id: string, options: Record<string, unknown>], ModuleResult>("set_module_options");
export const moduleAction = callable<[id: string, action: string, args?: Record<string, unknown>], ModuleResult>("module_action");
export const onRunningAppChanged = callable<[appId: string | null], { appId: string | null }>("on_running_app_changed");
export const restartSteamService = callable<[], { ok: boolean; error: string }>("restart_steam");
export const getLive = callable<[], LiveValues>("get_live");
export const backupSettings = callable<[], { name: string; dir: string }>("backup_settings");
export const listBackups = callable<[], { dir: string; backups: { name: string; size: number }[] }>("list_backups");
export const restoreBackup = callable<[name: string], { restored: string[] }>("restore_backup");
export const repairController = callable<[], { ok: boolean; error: string }>("repair_controller");

/** Verify the latest release in the backend, then hand it to Decky Loader's installer. */
export async function installUpdate(): Promise<void> {
  const a = await prepareUpdate();
  const backend = window.DeckyBackend;
  if (!backend?.callable) throw new Error("Decky install API not available");
  const install = backend.callable<[string, string, string, string, number], void>("utilities/install_plugin");
  // InstallType.UPDATE = 2 (decky-loader frontend enum)
  await install(a.artifact, a.name, a.version, a.hash, 2);
}
