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

/** One module's state; `D` is its details() (Partial: a module whose details fail reports only `error`). */
export interface ModuleStatus<D = any> {
  id: string;
  title: string;
  supported: boolean;
  toggle: boolean;
  enabled: boolean;
  state: ModuleState;
  message: string;
  details: Partial<D> & { error?: string };
  blockedBy?: string;
}

// ---- details() of each backend module (py_modules/allycompanion/modules/*.py) ----------------
export interface Option { id: string; label: string }
export interface PresetChoice { profile: string; voicing: string }
export interface PerAppPreset extends PresetChoice { enabled: boolean; name: string }
export interface SetupEvent { step: string; status: string; message: string; percent: number; index?: number; total?: number }
export interface ConvertEvent { status: string; message: string; percent: number }

export interface AudioDetails {
  setup: {
    done: boolean; xmlSha256: string | null; packageVersion: string | null; converterVersion: string | null;
    completedAt: string | null; extrasSignature: string | null; targetSink: string | null; xmlPresent: boolean;
    venvOk: boolean; presets: Record<string, Record<string, boolean>>; inProgress: boolean; last: SetupEvent | null;
    converting: boolean; convertLast: ConvertEvent | null;
  };
  enabledSetting: boolean;
  global: PresetChoice;
  perApp: Record<string, PerAppPreset>;
  extras: { autogain: boolean; dialog: boolean; regulator: boolean; virtualBass: boolean; preGainDb: number };
  dsp: { active: boolean; verified: boolean; activePreset: (PresetChoice & { preGainDb?: number }) | null; paused: boolean };
  headphones: boolean;
  codec: { codec: string; ssid: string; supported: boolean; model: string | null } | null;
  sink: { name: string; description: string } | null;
  lv2: { ok: boolean; missing: string[]; calf: boolean } | null;
  runningApp: string | null;
  resolved: PresetChoice & { source: "app" | "global"; appId: string | null };
  profiles: Option[];
  voicings: Option[];
  steps: string[];
}
export interface MicDetails { vad: number; target: string | null; active: boolean; verified: boolean }
export interface HeadphonesDetails {
  eq: { name?: string; source?: string; preamp?: number } | null;
  filters: number; output: string; running: boolean; runningOn: string | null;
}
export interface VibrationDetails {
  left: number; right: number; linked: boolean; override: number[] | null; enhanced: boolean; enhancedSupported: boolean;
  mirrorTriggers: boolean; mirrorSupported: boolean; hw: number[] | null; ffFilter: string; ffError: string;
}
export interface GyroDetails { mode: "simple" | "complex" | "deck"; override: string; steamCfgPresent: boolean; targets: string[]; deckUhid: boolean }
export interface GamepadLayoutDetails {
  nativeReady: boolean; shimActive: boolean; shimPatched: boolean | null; ui: UiPatchResult | null; restartPending: boolean;
}
export interface CpuBoostDetails {
  boost: string | null; capSlips: boolean; refreshOnCharger: boolean; overCapCores: number; policies: number; kicks: number;
  lastKick: string; override: boolean | null; watching: boolean;
}
export interface FanCurve { temps: number[]; pwm1: number[]; pwm2: number[] }
export interface FanDetails {
  profile: string; pwmEnable: (number | null)[]; rpm: (number | null)[]; temp: number | null; curve: FanCurve | null;
  snapshotProfiles: string[]; lastEvent: string; override: boolean; fixedByOs: boolean; floorFromC: number;
}
export interface HealthSample { d: string; h: number; e: number | null; c: number | null }
export interface BatteryDetails {
  capacity: number | null; status: string | null; healthPct: number | null; energyFullWh: number | null;
  energyDesignWh: number | null; cycles: number | null; powerW: number; chargeLimit: number | null;
  chargeLimitSupported: boolean; chargeLimitMin: number; mcuPowersave: boolean | null; bootSound: boolean | null;
  pendingReboot: boolean; fullOnce: boolean; history: HealthSample[];
}
export interface LightingValues { mode: string; color: string; color2: string; brightness: number; speed: string }
export interface LightingDetails extends LightingValues {
  enabled: boolean; shown: string; override: boolean; brightnessRaw: number | null; intensity: string | null;
}
export interface GameProfile {
  name?: string; lighting?: Partial<LightingValues>; vibration?: { left: number; right: number };
  cpuBoost?: { boost: boolean }; fan?: { curve: FanCurve }; performance?: { profile: string };
}
export interface ProfilesDetails {
  apps: Record<string, GameProfile>; runningApp: string | null; performanceProfiles: string[]; performanceProfile: string | null;
}
export interface NewsItem {
  id: string; kind: "steamos" | "bios" | "firmware" | "issue"; title?: string; version?: string; channel?: string;
  body?: string; size?: string; sha256?: string; url: string | null; date?: number | string; newer: boolean; highlights?: string[];
}
export interface NewsDetails {
  items: NewsItem[]; unseen: string[]; fetchedAt: number | null; error: string | null; channel: string | null;
  installed: { steamos: string; bios: string };
}

export interface ModuleDetails {
  audio: AudioDetails; mic: MicDetails; headphones: HeadphonesDetails; vibration: VibrationDetails; gyro: GyroDetails;
  gamepad_layout: GamepadLayoutDetails; cpu_boost: CpuBoostDetails; fan: FanDetails; battery: BatteryDetails;
  lighting: LightingDetails; profiles: ProfilesDetails; news: NewsDetails;
}
export type ModuleId = keyof ModuleDetails;
export type ModuleStatuses = { [K in ModuleId]?: ModuleStatus<ModuleDetails[K]> };

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
  modules: ModuleStatuses;
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

export interface LiveValues {
  cpu: { boost: boolean; avgMHz: number | null; maxMHz: number | null; capMHz: number | null; hwMaxMHz: number | null;
    cores: number; overCap: number; tempC: number | null };
  gpu: { tempC: number | null; clockMHz: number | null; busyPct: number | null; apuW: number | null };
  fansRpm: (number | null)[];
  battery: { capacity: number | null; status: string | null; powerW: number | null };
  platformProfile: string | null;
  pptW: (number | null)[];
}
