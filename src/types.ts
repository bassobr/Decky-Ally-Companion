export interface DeviceInfo {
  board: string;
  model: string | null;
  supported: boolean;
  bios: string;
  mcu: string | null;
  os: string;
  osId: string;
  osVersion: string;
  osBuild: string;
  kernel: string;
}

export interface StackInfo {
  inputplumber: { present: boolean; version: string | null };
  steamosManager: { present: boolean; deviceModel: [string, string] | null };
  hidAsusAlly: boolean;
  led: boolean;
  asusArmoury: boolean;
}

export type ModuleState =
  | "applied"
  | "not_applied"
  | "error"
  | "stale"
  | "restart_pending"
  | "not_supported"
  | "info"
  | "blocked";

export interface ModuleStatus {
  id: string;
  title: string;
  supported: boolean;
  toggle: boolean;
  enabled: boolean;
  state: ModuleState;
  message: string;
  details: Record<string, any>;
  blockedBy?: string;
}

export interface ModuleResult {
  ok: boolean;
  error: string;
  result: unknown;
  status: ModuleStatus;
}

export interface UpdateInfo {
  currentVersion: string;
  latestVersion: string | null;
  updateAvailable: boolean;
  releaseUrl: string | null;
  checkedAt: number | null;
  error: string | null;
}

export interface UpdateArtifact {
  artifact: string;
  name: string;
  version: string;
  hash: string;
  detail: string;
}

export interface PluginState {
  version: string;
  device: DeviceInfo;
  stack: StackInfo;
  conflicts: string[];
  modules: Record<string, ModuleStatus>;
  update: UpdateInfo;
}

/** Outcome of the UI half of the gamepad layout module (see layoutPatch.ts). */
export interface UiPatchResult {
  ok: boolean;
  stage?: string;
  error?: string;
  module?: string;
  wrapped?: string[];
  caps?: string[];
  art?: string;
}
