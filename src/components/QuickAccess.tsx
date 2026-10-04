import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { installUpdate } from "../backend";
import { usePluginState } from "../hooks/usePluginState";
import { openPage } from "../navigation";
import { warnings } from "../status";
import { t } from "../strings";
import { FRONTEND_VERSION } from "../version";

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

// The sidebar holds only what changes during a game; modules add their quick controls here.
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
