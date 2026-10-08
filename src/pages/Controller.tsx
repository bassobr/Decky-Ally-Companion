import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, DropdownItem, Field, SliderField, ToggleField } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { appName } from "../appWatcher";
import { repairController } from "../backend";
import { InfoField, isActive, ModuleToggle } from "../components/ModuleRow";
import { useDebounced } from "../hooks/useDebounced";
import { restartSteam, withSteamRestart } from "../steamRestart";
import { mod, useModule } from "../store";
import type { GamepadLayoutDetails, GyroDetails, ModuleStatus, VibrationDetails } from "../types";

const GYRO_MODES = [
  { data: "simple", label: "Simple", description: "Right in regular games. In Valve's Source games (Portal 2, Half-Life 2) Yaw and Roll stay swapped." },
  { data: "complex", label: "Complex", description: "Right everywhere. Steam restarts when this mode is switched on or off." },
  { data: "deck", label: "Deck emulation", description: "Right everywhere by presenting a generic controller to Steam. Layouts saved for the ROG Ally no longer apply." },
];

function Vibration({ m }: { m: ModuleStatus<VibrationDetails> }) {
  const d = m.details;
  const game = useModule("profiles")?.details.runningApp ?? null;
  const [left, setLeft] = useState<number>(d.left ?? 50);
  const [right, setRight] = useState<number>(d.right ?? 50);
  useEffect(() => { setLeft(d.left ?? 50); setRight(d.right ?? 50); }, [d.left, d.right]);
  // one sender per slider: a shared one would drop the left value when the right one follows quickly
  const sendLeft = useDebounced((v: number) => void mod.options("vibration", { left: v }));
  const sendRight = useDebounced((v: number) => void mod.options("vibration", { right: v }));
  const usable = isActive(m);
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Vibration</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Lower grip vibration" description="The factory setting is 100 %, which most games overdo."
        onChange={(on) => void mod.enable("vibration", on)} />
      {m.enabled && usable && d.override && (
        <Field focusable label={`${game ? appName(game) : "The running game"} has its own strength (${d.override[0]} %)`}
          description="Change it under Game profiles. The sliders below set the strength for everything else." />
      )}
      {m.enabled && usable && (
        <>
          <ToggleField label="Same strength for both grips" checked={!!d.linked}
            onChange={(on) => void mod.options("vibration", { linked: on })} />
          <SliderField label={d.linked ? "Strength" : "Left grip"} value={left} min={0} max={100} step={5} showValue valueSuffix=" %"
            onChange={(v) => { setLeft(v); if (d.linked) setRight(v); sendLeft(v); }} />
          {!d.linked && (
            <SliderField label="Right grip" value={right} min={0} max={100} step={5} showValue valueSuffix=" %"
              onChange={(v) => { setRight(v); sendRight(v); }} />
          )}
        </>
      )}
      {usable && (
        <ButtonItem layout="below" onClick={() => void mod.action("vibration", "test", { duration_ms: 500 })}>
          Test vibration
        </ButtonItem>
      )}
      {usable && d.enhancedSupported && (
        <ToggleField label="Enhanced Vibration" checked={!!d.enhanced}
          description="Armoury Crate's Xbox-recommended waveform. Rumble from games is capped to the controller's range while it is on."
          onChange={(on) => void mod.action("vibration", "set_enhanced", { on })} />
      )}
      {usable && d.mirrorSupported && (
        <ToggleField label="Rumble on the triggers" checked={!!d.mirrorTriggers}
          description={d.ffError || "Copies grip rumble onto the impulse triggers, which SteamOS never drives otherwise."}
          onChange={(on) => void mod.action("vibration", "set_mirror", { on })} />
      )}
    </DialogControlsSection>
  );
}

function Gyro({ m }: { m: ModuleStatus<GyroDetails> }) {
  const d = m.details;
  const mode = d.mode ?? "simple";
  const needsRestart = (on: boolean, md: string) => (on && md === "complex") !== !!d.steamCfgPresent;
  const toggle = async (on: boolean) => {
    if (needsRestart(on, mode)) {
      await withSteamRestart("Steam reads this gyro setting only when it starts. Apply and restart Steam now?",
        () => mod.enable("gyro", on));
    } else {
      await mod.enable("gyro", on);
    }
  };
  const setMode = async (md: string) => {
    if (m.enabled && needsRestart(true, md)) {
      await withSteamRestart("Steam reads this gyro setting only when it starts. Apply and restart Steam now?",
        () => mod.options("gyro", { mode: md }));
    } else {
      await mod.options("gyro", { mode: md });
    }
  };
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Gyro</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Fix gyro axes" description="Steam Input reads the Ally's gyro axes tilted."
        onChange={(on) => void toggle(on)} />
      {isActive(m) && (
        <DropdownItem label="Mode" description={GYRO_MODES.find((x) => x.data === mode)?.description}
          rgOptions={GYRO_MODES.map((x) => ({ data: x.data, label: x.label }))} selectedOption={mode}
          onChange={(o) => void setMode(o.data)} />
      )}
      {isActive(m) && m.enabled && (d.targets?.length ?? 0) > 0 && !d.deckUhid && (
        <Field label="InputPlumber does not use the deck-uhid target" description={`Targets: ${(d.targets ?? []).join(", ")}. The fix assumes deck-uhid.`} focusable />
      )}
    </DialogControlsSection>
  );
}

function Layout({ m }: { m: ModuleStatus<GamepadLayoutDetails> }) {
  const d = m.details;
  const toggle = async (on: boolean) => {
    if (on !== !!d.shimActive) {
      await withSteamRestart("Steam builds the controller layout only when it starts. Apply and restart Steam now?",
        () => mod.enable("gamepad_layout", on));
    } else {
      await mod.enable("gamepad_layout", on);
    }
  };
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Steam Input layout</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Hide inputs the Ally does not have"
        description="Trackpads, touch-sensitive sticks and the lower pair of rear buttons disappear from Steam's controller settings."
        onChange={(on) => void toggle(on)} />
    </DialogControlsSection>
  );
}

async function repair() {
  const r = await repairController();
  toaster.toast({ title: "Ally Companion", body: r.ok ? "Controller reconnected" : `Repair failed: ${r.error}` });
}

export function Controller() {
  const vib = useModule("vibration");
  const gyro = useModule("gyro");
  const layout = useModule("gamepad_layout");
  const pending = [gyro, layout].some((m) => m?.state === "restart_pending");
  return (
    <DialogBody>
      {pending && (
        <DialogControlsSection>
          <ButtonItem layout="below" description="A change only takes effect after Steam restarts." onClick={() => void restartSteam()}>
            Restart Steam now
          </ButtonItem>
        </DialogControlsSection>
      )}
      {vib && <Vibration m={vib} />}
      {gyro && <Gyro m={gyro} />}
      {layout && <Layout m={layout} />}
      <DialogControlsSection>
        <DialogControlsSectionHeader>Repair</DialogControlsSectionHeader>
        <ButtonItem layout="below" description="Restarts InputPlumber and sends vibration and lighting to the controller again. Use it when the controller hangs after sleep."
          onClick={() => void repair()}>
          Reconnect the controller
        </ButtonItem>
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>Sticks and buttons</DialogControlsSectionHeader>
        <InfoField label="Deadzones, response curves, remapping" value="Steam Input, per game" />
      </DialogControlsSection>
    </DialogBody>
  );
}
