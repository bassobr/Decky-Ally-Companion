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

export interface ModuleStatus {
  id: string;
  title: string;
  supported: boolean;
  reason: string;
  error: string | null;
  state: Record<string, unknown>;
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
  modules: Record<string, ModuleStatus>;
  update: UpdateInfo;
}
