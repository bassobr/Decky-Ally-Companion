import { Field, ToggleField } from "@decky/ui";
import type { ModuleStatus } from "../types";

const STATE_TEXT: Record<string, string> = {
  applied: "Active",
  not_applied: "Not applied",
  error: "Error",
  stale: "Needs update",
  restart_pending: "Restart Steam to apply",
  not_supported: "Not supported",
  blocked: "Blocked",
  info: "",
};

/** One-line summary of a module's state for descriptions. */
export function stateLine(m: ModuleStatus): string {
  if (!m.supported) return `Not supported: ${m.message}`;
  if (m.state === "blocked") return `${m.blockedBy} is installed and drives the same hardware. Uninstall it in Decky.`;
  if (m.toggle && !m.enabled && m.state !== "restart_pending") return m.message || "Off";
  const base = STATE_TEXT[m.state] ?? m.state;
  return m.message ? (base ? `${base}: ${m.message}` : m.message) : base;
}

export function isActive(m?: ModuleStatus): boolean {
  return !!m && m.supported && m.state !== "blocked";
}

/** The switch of a toggle module with its state underneath. */
export function ModuleToggle({ m, label, description, onChange }: {
  m: ModuleStatus;
  label: string;
  description?: string;
  onChange: (on: boolean) => void;
}) {
  const usable = isActive(m);
  const state = stateLine(m);
  return (
    <ToggleField label={label} checked={m.enabled} disabled={!usable} onChange={onChange}
      description={[description, state].filter(Boolean).join(" · ")} />
  );
}

export function InfoField({ label, value }: { label: string; value: string | number | null | undefined }) {
  return <Field label={label} focusable>{value === null || value === undefined || value === "" ? "–" : String(value)}</Field>;
}
