import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, DropdownItem, Field, SliderField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { appName } from "../appWatcher";
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
  return parts.join(" · ");
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
          <Field focusable label="No game is running" description="Start a game and open this page to give it its own lighting and vibration." />
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
