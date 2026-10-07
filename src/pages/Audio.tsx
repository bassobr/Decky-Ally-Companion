import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, DropdownItem, Field, ProgressBarWithInfo, SliderField, TextField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { appName } from "../appWatcher";
import { InfoField, isActive, ModuleToggle } from "../components/ModuleRow";
import { useDebounced } from "../hooks/useDebounced";
import { confirm } from "../steamRestart";
import { mod, useModule } from "../store";
import type { AudioDetails, ModuleStatus, Option, PerAppPreset, PresetChoice } from "../types";

type Setup = AudioDetails["setup"];

const STEP_LABELS: Record<string, string> = {
  hardware: "Check hardware",
  resolve: "Locate ASUS package",
  download: "Download",
  extract: "Extract tuning",
  venv: "Prepare converter",
  convert: "Convert presets",
  activate: "Activate",
};

const labelOf = (list: Option[], id?: string) => list.find((x) => x.id === id)?.label ?? id ?? "–";

export function presetLabel(d: Partial<AudioDetails>, p?: { profile?: string; voicing?: string } | null): string {
  if (!p?.profile) return "–";
  return `${labelOf(d.profiles ?? [], p.profile)} · ${labelOf(d.voicings ?? [], p.voicing)}`;
}

function Setup({ m }: { m: ModuleStatus<AudioDetails> }) {
  const d = m.details;
  const s: Partial<Setup> = d.setup ?? {};
  const last = s.last;
  const unsupported = d.codec && !d.codec.supported;
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Setup</DialogControlsSectionHeader>
      {!s.done && !s.inProgress && (
        <Field focusable label="The Dolby tuning has to be downloaded and converted once"
          description="Downloads ASUS' Dolby package (about 10 MB) onto this device, extracts the tuning for its codec and converts it into PipeWire presets. A Python environment with numpy/scipy (about 220 MB) is created once. Nothing leaves the device." />
      )}
      {s.inProgress && last && (
        <>
          <ProgressBarWithInfo nProgress={last.percent} sOperationText={`${STEP_LABELS[last.step] ?? last.step}: ${last.message}`} />
          <ButtonItem layout="below" onClick={() => void mod.action("audio", "cancel_setup")}>Cancel</ButtonItem>
        </>
      )}
      {!s.inProgress && last && last.status === "error" && <Field focusable label="Setup failed" description={last.message} />}
      {!s.inProgress && (
        <ButtonItem layout="below" description={s.done ? `Package ${s.packageVersion ?? "?"} · converter ${s.converterVersion ?? "?"}` : undefined}
          onClick={() => void mod.action("audio", "run_setup", { force: !!s.done, allowUnsupported: !!unsupported })}>
          {s.done ? "Run setup again" : unsupported ? "Try anyway (device not in the list)" : "Run setup"}
        </ButtonItem>
      )}
    </DialogControlsSection>
  );
}

function Presets({ m }: { m: ModuleStatus<AudioDetails> }) {
  const d = m.details;
  const profiles = (d.profiles ?? []).map((p: Option) => ({ data: p.id, label: p.label }));
  const voicings = (d.voicings ?? []).map((v: Option) => ({ data: v.id, label: v.label }));
  const appId: string | null = d.runningApp ?? null;
  const per = appId ? d.perApp?.[appId] : undefined;
  const g: Partial<PresetChoice> = d.global ?? {};
  const setPer = (entry: unknown) => void mod.action("audio", "set_per_app", { appId, entry });
  return (
    <>
      <DialogControlsSection>
        <DialogControlsSectionHeader>Preset</DialogControlsSectionHeader>
        <DropdownItem label="Profile" rgOptions={profiles} selectedOption={g.profile}
          onChange={(o) => void mod.action("audio", "set_global", { profile: o.data, voicing: g.voicing })} />
        <DropdownItem label="Voicing" rgOptions={voicings} selectedOption={g.voicing}
          onChange={(o) => void mod.action("audio", "set_global", { profile: g.profile, voicing: o.data })} />
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{appId ? `This game: ${appName(appId)}` : "Per game"}</DialogControlsSectionHeader>
        {appId ? (
          <>
            <ToggleField label="Own preset for this game" checked={!!per}
              onChange={(on) => setPer(on ? { profile: d.resolved?.profile ?? g.profile, voicing: d.resolved?.voicing ?? g.voicing,
                enabled: true, name: appName(appId) } : null)} />
            {per && (
              <>
                <DropdownItem label="Profile" rgOptions={profiles} selectedOption={per.profile} onChange={(o) => setPer({ ...per, profile: o.data })} />
                <DropdownItem label="Voicing" rgOptions={voicings} selectedOption={per.voicing} onChange={(o) => setPer({ ...per, voicing: o.data })} />
              </>
            )}
          </>
        ) : (
          <Field focusable label="No game is running" description="Per-game presets are set here or in the Quick Access panel while a game runs." />
        )}
        {Object.entries(d.perApp ?? {}).filter(([id]) => id !== appId).map(([id, e]: [string, PerAppPreset]) => (
          <ButtonItem key={id} layout="inline" label={`${e.name || id}: ${presetLabel(d, e)}`}
            onClick={() => void (async () => {
              if (await confirm("Remove game preset", `Remove the sound preset for ${e.name || id}?`, "Remove")) {
                await mod.action("audio", "set_per_app", { appId: id, entry: null });
              }
            })()}>
            Remove
          </ButtonItem>
        ))}
      </DialogControlsSection>
    </>
  );
}

function Extras({ m }: { m: ModuleStatus<AudioDetails> }) {
  const d = m.details;
  const x: Partial<AudioDetails["extras"]> = d.extras ?? {};
  const s: Partial<Setup> = d.setup ?? {};
  const busy = !!(s.inProgress || s.converting);
  const [gain, setGain] = useState<number>(x.preGainDb ?? 0);
  useEffect(() => setGain(x.preGainDb ?? 0), [x.preGainDb]);
  const sendGain = useDebounced((v: number) => void mod.action("audio", "set_extras", { extras: { preGainDb: v } }), 600);
  const set = (extras: Record<string, unknown>) => void mod.action("audio", "set_extras", { extras });
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Extras</DialogControlsSectionHeader>
      {s.converting && s.convertLast && (
        <ProgressBarWithInfo nProgress={s.convertLast.percent} sOperationText={`Regenerating presets: ${s.convertLast.message}`} />
      )}
      <ToggleField label="Volume leveler" description="Dolby loudness leveling. Turn off if you hear pumping." checked={!!x.autogain}
        disabled={busy} onChange={(v) => set({ autogain: v })} />
      <ToggleField label="Dialog enhancer" checked={!!x.dialog} disabled={busy} onChange={(v) => set({ dialog: v })} />
      <ToggleField label="Regulator" description="Dolby's overdrive protection. Only disable if the volume wobbles." checked={!!x.regulator}
        disabled={busy} onChange={(v) => set({ regulator: v })} />
      {d.lv2?.calf && (
        <ToggleField label="Virtual bass (experimental)" checked={!!x.virtualBass} disabled={busy} onChange={(v) => set({ virtualBass: v })} />
      )}
      <SliderField label="Pre-gain" value={gain} min={-6} max={6} step={1} showValue valueSuffix=" dB" notchCount={13}
        disabled={!!s.inProgress} onChange={(v) => { setGain(v); sendGain(v); }} />
    </DialogControlsSection>
  );
}

function Microphone() {
  const m = useModule("mic");
  const [vad, setVad] = useState<number>(m?.details.vad ?? 50);
  useEffect(() => setVad(m?.details.vad ?? 50), [m?.details.vad]);
  const send = useDebounced((v: number) => void mod.options("mic", { vad: v }), 600);
  if (!m || !m.supported) return null;
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Microphone</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Noise suppression"
        description="RNNoise cleans the internal microphone; the cleaned one becomes the default microphone while this is on."
        onChange={(on) => void mod.enable("mic", on)} />
      {m.enabled && isActive(m) && (
        <SliderField label="Voice threshold" value={vad} min={0} max={95} step={5} showValue valueSuffix=" %"
          description="Higher: more silence between words, but quiet speech can be cut."
          onChange={(v) => { setVad(v); send(v); }} />
      )}
    </DialogControlsSection>
  );
}

function Headphones() {
  const m = useModule("headphones");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ name: string; path: string; source: string }[] | null>(null);
  const [outputs, setOutputs] = useState<{ name: string; description: string }[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (m?.enabled) void mod.action("headphones", "outputs").then((r) => setOutputs((r.result as any[]) ?? []));
  }, [m?.enabled]);
  if (!m || !m.supported) return null;
  const d = m.details;
  const search = async () => {
    setBusy(true);
    try {
      const r = await mod.action("headphones", "search", { query });
      setResults((r.result as any[]) ?? []);
    } finally {
      setBusy(false);
    }
  };
  const select = async (e: { name: string; path: string; source: string }) => {
    setBusy(true);
    try {
      await mod.action("headphones", "select", { path: e.path, name: e.name, source: e.source });
      setResults(null);
    } finally {
      setBusy(false);
    }
  };
  const outputOptions = [{ data: "wired", label: "Wired (3.5 mm jack)" }, ...outputs.map((o) => ({ data: o.name, label: o.description }))];
  if (d.output && d.output !== "wired" && !outputs.some((o) => o.name === d.output)) outputOptions.push({ data: d.output, label: `${d.output} (not connected)` });
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Headphones</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Headphone EQ"
        description="Correction profiles from AutoEQ for your headphone model. Runs only while the headphones are in use."
        onChange={(on) => void mod.enable("headphones", on)} />
      {m.enabled && isActive(m) && (
        <>
          <Field focusable label="Profile" description={d.eq ? `${d.eq.name} · measured by ${d.eq.source} · ${d.filters} filters, preamp ${d.eq.preamp} dB` : "None yet"} />
          <DropdownItem label="Headphones on" rgOptions={outputOptions} selectedOption={d.output ?? "wired"}
            onChange={(o) => void mod.action("headphones", "set_output", { output: o.data })} />
          <TextField label="Search your headphones" value={query} onChange={(e) => setQuery(e.target.value)} />
          <ButtonItem layout="below" disabled={busy || query.trim().length < 2} onClick={() => void search()}>Search AutoEQ</ButtonItem>
          {results && results.length === 0 && <Field focusable label="Nothing found" />}
          {(results ?? []).map((e) => (
            <ButtonItem key={e.path} layout="inline" label={e.name} description={e.source} disabled={busy} onClick={() => void select(e)}>
              Use
            </ButtonItem>
          ))}
          {d.eq && (
            <ButtonItem layout="below" disabled={busy} onClick={() => void mod.action("headphones", "clear")}>Remove the profile</ButtonItem>
          )}
        </>
      )}
    </DialogControlsSection>
  );
}

export function Audio() {
  const m = useModule("audio");
  if (!m) return null;
  const d = m.details;
  const done = !!d.setup?.done;
  return (
    <DialogBody>
      <DialogControlsSection>
        <DialogControlsSectionHeader>Speakers</DialogControlsSectionHeader>
        <ModuleToggle m={m} label="Dolby speaker tuning" description="Off: untreated speakers, for A/B comparison."
          onChange={(on) => void mod.enable("audio", on)} />
        {isActive(m) && done && (
          <>
            <InfoField label="Playing with" value={`${presetLabel(d, d.dsp?.activePreset)}${d.resolved?.source === "app" ? " (this game)" : ""}`} />
            <InfoField label="Filter chain" value={d.dsp?.paused ? "paused: headphones" : d.dsp?.active ? (d.dsp?.verified ? "running" : "starting") : "stopped"} />
          </>
        )}
      </DialogControlsSection>
      {isActive(m) && <Setup m={m} />}
      {isActive(m) && done && <Presets m={m} />}
      {isActive(m) && done && <Extras m={m} />}
      <Microphone />
      <Headphones />
    </DialogBody>
  );
}
