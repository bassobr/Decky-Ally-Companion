import { t } from "./strings";
import type { PluginState } from "./types";

/** Problems worth a glance from the sidebar; details live on the Overview page. */
export function warnings(s: PluginState): string[] {
  const out: string[] = [];
  if (!s.device.supported) out.push(`${t.unsupported} (${s.device.board || "?"})`);
  if (!s.stack.inputplumber.present) out.push(`${t.inputplumber} ${t.notRunning}`);
  for (const m of Object.values(s.modules)) if (m.error) out.push(`${m.title}: ${m.error}`);
  return out;
}
