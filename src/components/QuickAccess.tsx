import { ButtonItem, Field, PanelSection, PanelSectionRow, SliderField } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { installUpdate } from "../backend";
import { useDebounced } from "../hooks/useDebounced";
import { openPage } from "../navigation";
import { warnings } from "../status";
import { restartSteam } from "../steamRestart";
import { mod, usePluginState } from "../store";
import { t } from "../strings";
import { FRONTEND_VERSION } from "../version";
import { isActive } from "./ModuleRow";

let reopenTried = false;

/** After an update Decky has loaded the new bundle but keeps showing this old panel; select the plugin again. */
function reopenWithNewUi(): void {
  if (reopenTried) return;
  reopenTried = true;
  try {
    window.DeckyPluginLoader?.deckyState?.setActivePlugin?.(t.title);
  } catch {
    /* the stale-UI row stays as a hint */
  }
}

function LightBrightness() {
  const m = usePluginState().state?.modules.lighting;
  const [value, setValue] = useState<number>(m?.details.brightness ?? 60);
  useEffect(() => setValue(m?.details.brightness ?? 60), [m?.details.brightness]);
  const send = useDebounced((v: number) => void mod.options("lighting", { brightness: v }));
  if (!m || !m.enabled || !isActive(m) || m.details.mode === "off") return null;
  return (
    <PanelSectionRow>
      <SliderField label={t.lighting} value={value} min={0} max={100} step={5} showValue valueSuffix=" %"
        onChange={(v) => { setValue(v); send(v); }} />
    </PanelSectionRow>
  );
}

// The sidebar holds only what changes during a game; everything else is in the fullscreen view.
export function QuickAccess() {
  const { state, error, refresh } = usePluginState();
  const [busy, setBusy] = useState(false);
  const stale = !!state && state.version !== FRONTEND_VERSION;

  useEffect(() => {
    if (stale) reopenWithNewUi();
  }, [stale]);

  if (error || !state) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label={error ? t.backendError : t.title} description={error ?? undefined} />
        </PanelSectionRow>
        {error && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => void refresh()}>{t.retry}</ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
    );
  }

  const w = warnings(state);
  const restartPending = Object.values(state.modules).some((m) => m.state === "restart_pending");
  const onUpdate = async () => {
    setBusy(true);
    try {
      await installUpdate();
    } catch (e) {
      toaster.toast({ title: t.title, body: `${t.updateFailed}: ${String(e)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection>
      <PanelSectionRow>
        <Field label={state.device.model ?? t.unsupported} description={w.length ? w.join(" · ") : t.allGood}
          focusable onActivate={() => openPage("overview")} />
      </PanelSectionRow>
      {stale && (
        <PanelSectionRow>
          <Field label={t.staleUi} />
        </PanelSectionRow>
      )}
      {restartPending && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void restartSteam()}>Restart Steam to apply</ButtonItem>
        </PanelSectionRow>
      )}
      <LightBrightness />
      {state.update.updateAvailable && state.update.latestVersion && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => void onUpdate()}>
            {t.updateTo(state.update.latestVersion)}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => openPage("overview")}>{t.allSettings}</ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
