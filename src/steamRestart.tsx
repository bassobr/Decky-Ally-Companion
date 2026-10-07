import { ConfirmModal, showModal } from "@decky/ui";
import { restartSteamService } from "./backend";

/**
 * One restart for everything that needs it. The backend restarts Steam's user service, which gives
 * the client a fresh environment (the gamepad layout shim comes in through LD_PRELOAD); Steam's own
 * restart keeps the old environment and is only the fallback outside gaming mode.
 */
export async function restartSteam(): Promise<void> {
  try {
    const r = await restartSteamService();
    if (r.ok) return;
    console.warn("[Ally Companion] service restart unavailable:", r.error);
  } catch (e) {
    console.warn("[Ally Companion] service restart failed:", e);
  }
  SteamClient.User.StartRestart(false);
}

export function confirm(title: string, description: string, ok: string, cancel = "Cancel"): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    const pick = (v: boolean) => {
      if (done) return;
      done = true;
      resolve(v);
    };
    showModal(
      <ConfirmModal strTitle={title} strDescription={description} strOKButtonText={ok} strCancelButtonText={cancel}
        onOK={() => pick(true)} onCancel={() => pick(false)} />,
    );
  });
}

/** Ask, apply the change, then restart Steam; false when the user declined or the change failed
 * (the module's error is already on screen then, and a restart would only interrupt the game). */
export async function withSteamRestart(text: string, change: () => Promise<{ ok: boolean } | void>): Promise<boolean> {
  if (!(await confirm("Restart Steam", text, "Apply and restart"))) return false;
  const result = await change();
  if (result && !result.ok) return false;
  await restartSteam();
  return true;
}
