import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, DropdownItem, Field, SliderField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { appName } from "../appWatcher";
import { type Curve, CurveEditor } from "../components/CurveEditor";
import { isActive } from "../components/ModuleRow";
import { useDebounced } from "../hooks/useDebounced";
import { mod, usePluginState } from "../store";
import { presetLabel } from "./Audio";
import { pickColor, Swatch } from "./Lighting";

const LIGHT_MODES = [
  { data: "static", label: "Static" },
  { data: "breathing", label: "Breathing" },
  { data: "cycle", label: "Colour cycle" },
  { data: "rainbow", label: "Rainbow" },
  { data: "off", label: "Off" },
];

/** "sound Movie · Warm · light static #00ff00 · vibration 30 %" */
function summary(e: any, audioEntry: any, audioDetails: Record<string, any>): string {
  const parts: string[] = [];
  if (audioEntry) parts.push(`sound ${presetLabel(audioDetails, audioEntry)}`);
  if (e?.lighting) parts.push(`light ${e.lighting.mode}${e.lighting.color ? ` ${e.lighting.color}` : ""}`);
  if (e?.vibration) parts.push(`vibration ${e.vibration.left} %`);
  if (e?.performance) parts.push(e.performance.profile);
  if (e?.cpuBoost) parts.push(`boost ${e.cpuBoost.boost ? "on" : "off"}`);
  if (e?.fan) parts.push("own fan curve");
  return parts.join(" · ");
}

const BOOST = [
  { data: "default", label: "As set on the Power page" },
  { data: "off", label: "Off (cooler, quieter)" },
  { data: "on", label: "On (faster)" },
];

/** Performance profile, CPU boost and fan curve while this game runs. */
function Performance({ appId, entry, set }: { appId: string; entry: any; set: (part: string, values: unknown) => void }) {
  const s = usePluginState().state;
  const prof = s?.modules.profiles;
  const boost = s?.modules.cpu_boost;
  const fan = s?.modules.fan;
  const profiles: string[] = prof?.details.performanceProfiles ?? [];
  const perf = entry.performance?.profile ?? "default";
  const boostSel = entry.cpuBoost ? (entry.cpuBoost.boost ? "on" : "off") : "default";
  const curve = (entry.fan?.curve ?? fan?.details.curve) as Curve | null;
  return (
    <>
      {profiles.length > 0 && (
        <DropdownItem label="Performance profile" rgOptions={[{ data: "default", label: "As set in Steam" },
          ...profiles.map((p) => ({ data: p, label: p }))]} selectedOption={perf}
          description={perf !== "default" && perf !== "performance" ? "Steam's TDP limit only works in the performance profile." : undefined}
          onChange={(o) => set("performance", o.data === "default" ? null : { profile: o.data })} />
      )}
      {boost && isActive(boost) && (
        <DropdownItem label="CPU boost" rgOptions={BOOST} selectedOption={boostSel}
          onChange={(o) => set("cpuBoost", o.data === "default" ? null : { boost: o.data === "on" })} />
      )}
      {fan && isActive(fan) && (
        <>
          <ToggleField label="Own fan curve" checked={!!entry.fan}
            description={entry.fan ? "Pinned while this game runs." : "Starts from the curve that is active now."}
            onChange={(on) => set("fan", on && curve ? { curve } : null)} />
          {entry.fan && curve && (
            <CurveEditor key={appId} curve={curve} applyLabel="Save the curve for this game"
              onApply={(c) => set("fan", { curve: c })} />
          )}
        </>
      )}
    </>
  );
}

function ThisGame({ appId }: { appId: string }) {
  const s = usePluginState().state;
  const prof = s?.modules.profiles;
  const light = s?.modules.lighting;
  const vib = s?.modules.vibration;
  const entry = prof?.details.apps?.[appId] ?? {};
  const name = appName(appId);
  const set = (part: string, values: unknown) => void mod.action("profiles", "set_app", { appId, part, values, name });
  const l = entry.lighting;
  const [bright, setBright] = useState<number>(l?.brightness ?? light?.details.brightness ?? 60);
  const [strength, setStrength] = useState<number>(entry.vibration?.left ?? vib?.details.left ?? 50);
  useEffect(() => setBright(l?.brightness ?? 60), [l?.brightness]);
  useEffect(() => setStrength(entry.vibration?.left ?? 50), [entry.vibration?.left]);
  const sendBright = useDebounced((v: number) => set("lighting", { ...l, brightness: v }));
  const sendStrength = useDebounced((v: number) => set("vibration", { left: v, right: v }));
  const baseLight = () => ({ mode: light?.details.mode ?? "static", color: light?.details.color ?? "#ffffff",
    color2: light?.details.color2 ?? "#000000", brightness: light?.details.brightness ?? 60, speed: light?.details.speed ?? "medium" });
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>{`This game: ${name}`}</DialogControlsSectionHeader>
      {light && isActive(light) && (
        <>
          <ToggleField label="Own lighting" checked={!!l} description={!light.enabled ? "Lighting control is off on the Lighting page." : undefined}
            onChange={(on) => set("lighting", on ? baseLight() : null)} />
          {l && (
            <>
              <DropdownItem label="Mode" rgOptions={LIGHT_MODES} selectedOption={l.mode} onChange={(o) => set("lighting", { ...l, mode: o.data })} />
              {["static", "breathing", "cycle"].includes(l.mode) && (
                <ButtonItem layout="inline" label="Colour" onClick={() => pickColor("Colour", l.color, (c) => set("lighting", { ...l, color: c }))}>
                  <Swatch color={l.color} />
                </ButtonItem>
              )}
              <SliderField label="Brightness" value={bright} min={0} max={100} step={5} showValue valueSuffix=" %"
                onChange={(v) => { setBright(v); sendBright(v); }} />
            </>
          )}
        </>
      )}
      {vib && isActive(vib) && (
        <>
          <ToggleField label="Own vibration strength" checked={!!entry.vibration}
            description={!vib.enabled ? "Lower grip vibration is off on the Controller page." : undefined}
            onChange={(on) => set("vibration", on ? { left: strength, right: strength } : null)} />
          {entry.vibration && (
            <SliderField label="Strength" value={strength} min={0} max={100} step={5} showValue valueSuffix=" %"
              onChange={(v) => { setStrength(v); sendStrength(v); }} />
          )}
        </>
      )}
      <Performance appId={appId} entry={entry} set={set} />
      <Field focusable label="Sound" description="Per-game speaker presets are set on the Audio page or in the Quick Access panel." />
    </DialogControlsSection>
  );
}

export function Profiles() {
  const s = usePluginState().state;
  const prof = s?.modules.profiles;
  const audio = s?.modules.audio;
  if (!prof) return null;
  const appId: string | null = prof.details.runningApp ?? null;
  const apps: Record<string, any> = prof.details.apps ?? {};
  const audioApps: Record<string, any> = audio?.details.perApp ?? {};
  const ids = Array.from(new Set([...Object.keys(apps), ...Object.keys(audioApps)])).filter((id) => id !== appId);
  return (
    <DialogBody>
      {appId ? <ThisGame appId={appId} /> : (
        <DialogControlsSection>
          <Field focusable label="No game is running"
            description="Start a game and open this page to give it its own lighting, vibration, performance profile, CPU boost and fan curve." />
        </DialogControlsSection>
      )}
      <DialogControlsSection>
        <DialogControlsSectionHeader>Saved games</DialogControlsSectionHeader>
        {ids.length === 0 && <Field focusable label="None yet" />}
        {ids.map((id) => {
          const audioEntry = audioApps[id];
          return (
            <ButtonItem key={id} layout="inline" label={apps[id]?.name || audioEntry?.name || appName(id)}
              description={summary(apps[id], audioEntry, audio?.details ?? {})}
              onClick={() => {
                void mod.action("profiles", "remove_app", { appId: id });
                if (audioEntry) void mod.action("audio", "set_per_app", { appId: id, entry: null });
              }}>
              Remove
            </ButtonItem>
          );
        })}
      </DialogControlsSection>
    </DialogBody>
  );
}
