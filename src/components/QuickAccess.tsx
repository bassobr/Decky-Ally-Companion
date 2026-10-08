import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, SliderField } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { appName } from "../appWatcher";
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

/** After an update Decky has loaded the new bundle but keeps showing this old panel; select the plugin again
 * once Decky is done (it loads a fresh install twice, about 2 s apart). */
function reopenWithNewUi(): void {
  if (reopenTried) return;
  reopenTried = true;
  window.setTimeout(() => {
    try {
      window.DeckyPluginLoader?.deckyState?.setActivePlugin?.(t.title);
    } catch {
      /* the hint stays */
    }
  }, 3000);
}

/** Decky keeps the replaced plugin selected in Quick Access after an update, also when that version
 * predates the hint above: select the current one when the selected entry is not it. */
export function selectCurrentPanel(): void {
  try {
    const ds = window.DeckyPluginLoader?.deckyState;
    const st = ds?.publicState?.();
    if (st?.activePlugin?.name === t.title && st.activePlugin !== st.plugins.find((p) => p.name === t.title)) {
      ds?.setActivePlugin?.(t.title);
    }
  } catch {
    /* the old panel stays until it is reopened */
  }
}

/** Speaker preset for what is running now: off, the default, or a profile (per game while one runs). */
function Sound() {
  const m = usePluginState().state?.modules.audio;
  if (!m || !isActive(m) || !m.details.setup?.done) return null;
  const d = m.details;
  const appId: string | null = d.runningApp ?? null;
  const per = appId ? d.perApp?.[appId] : undefined;
  const profiles: { id: string; label: string }[] = d.profiles ?? [];
  const OFF = "__off", DEFAULT = "__default";
  const options = [
    { data: OFF, label: "Off" },
    ...(appId ? [{ data: DEFAULT, label: `Default (${profiles.find((p) => p.id === d.global?.profile)?.label ?? "–"})` }] : []),
    ...profiles.map((p) => ({ data: p.id, label: p.label })),
  ];
  const selected = !m.enabled ? OFF : appId ? (per ? per.profile : DEFAULT) : d.global?.profile;
  const pick = async (v: string) => {
    if (v === OFF) return void mod.enable("audio", false);
    if (!m.enabled) await mod.enable("audio", true);
    if (v === DEFAULT) return void mod.action("audio", "set_per_app", { appId, entry: null });
    if (appId) {
      const voicing = per?.voicing ?? d.global?.voicing;
      return void mod.action("audio", "set_per_app", { appId, entry: { profile: v, voicing, enabled: true, name: appName(appId) } });
    }
    return void mod.action("audio", "set_global", { profile: v, voicing: d.global?.voicing });
  };
  return (
    <PanelSectionRow>
      <DropdownItem label={appId ? `Sound: ${appName(appId)}` : "Sound"} rgOptions={options} selectedOption={selected}
        onChange={(o) => void pick(o.data)} />
    </PanelSectionRow>
  );
}

function LightBrightness() {
  const s = usePluginState().state;
  const m = s?.modules.lighting;
  const appId = s?.modules.profiles?.details.runningApp ?? null;
  // a running game with its own lighting: its profile wins, so the slider changes that profile
  const own = appId && m?.details.override ? s?.modules.profiles?.details.apps?.[appId]?.lighting : undefined;
  const [value, setValue] = useState<number>(m?.details.brightness ?? 60);
  useEffect(() => setValue(m?.details.brightness ?? 60), [m?.details.brightness]);
  const send = useDebounced((v: number) => void (own && appId
    ? mod.action("profiles", "set_app", { appId, part: "lighting", values: { ...own, brightness: v }, name: appName(appId) })
    : mod.options("lighting", { brightness: v })));
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
  const { state, error, refresh, unloaded } = usePluginState();
  const [busy, setBusy] = useState(false);
  const stale = unloaded || (!!state && state.version !== FRONTEND_VERSION);

  useEffect(() => {
    if (stale) reopenWithNewUi();
  }, [stale]);

  if (stale) { // its buttons would act on frozen state, such as an update that is already installed
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label={t.staleUi} />
        </PanelSectionRow>
      </PanelSection>
    );
  }

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
      {restartPending && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void restartSteam()}>Restart Steam to apply</ButtonItem>
        </PanelSectionRow>
      )}
      <Sound />
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
