import { t } from "./strings";
import type { PluginState } from "./types";

/** Problems worth a glance from the sidebar; details live on the Overview page. */
export function warnings(s: PluginState): string[] {
  const out: string[] = [];
  if (!s.device.supported) out.push(`${t.unsupported} (${s.device.board || "?"})`);
  if (!s.stack.inputplumber.present) out.push(`${t.inputplumber} ${t.notRunning}`);
  for (const p of s.conflicts) out.push(`${p} is installed: its features stay with it until you uninstall it`);
  for (const m of Object.values(s.modules)) {
    if (m.state === "error" || m.state === "stale") out.push(`${m.title}: ${m.message}`);
    if (m.state === "restart_pending") out.push(`${m.title}: restart Steam to apply`);
  }
  return out;
}
