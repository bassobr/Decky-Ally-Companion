import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, Field, SliderField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { type Curve, CurveEditor } from "../components/CurveEditor";
import { FocusStop } from "../components/FocusStop";
import { InfoField, isActive, ModuleToggle } from "../components/ModuleRow";
import { useDebounced } from "../hooks/useDebounced";
import { batteryPower, useLive } from "../hooks/useLive";
import { mod, useModule } from "../store";
import type { ModuleStatus } from "../types";


function CpuBoost({ m }: { m: ModuleStatus }) {
  const d = m.details;
  const slips = d.capSlips !== false; // false: the cap survives charger events on this device
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>CPU</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Keep CPU boost off"
        description={slips
          ? "Cooler and quieter. The firmware drops the frequency cap on every charger plug; this re-sends it."
          : "Cooler and quieter: the CPU stays at its base clock."}
        onChange={(on) => void mod.enable("cpu_boost", on)} />
      {isActive(m) && m.enabled && (
        <>
          <ToggleField label="Re-send the cap on charger events" checked={slips && !!d.refreshOnCharger} disabled={!slips}
            description={slips ? undefined : "Not needed on this device: the cap survives charger events."}
            onChange={(on) => void mod.options("cpu_boost", { refreshOnCharger: on })} />
          <InfoField label="Cores above the cap" value={`${d.overCapCores ?? "–"} of ${d.policies ?? "–"}`} />
          <ButtonItem layout="below" disabled={!slips}
            description={d.lastKick ? `Last: ${d.lastKick} (${d.kicks} total)` : undefined}
            onClick={() => void mod.action("cpu_boost", "refresh_now")}>
            Re-send the cap now
          </ButtonItem>
        </>
      )}
    </DialogControlsSection>
  );
}

function FanCurve({ m }: { m: ModuleStatus }) {
  const curve = m.details.curve as Curve | null;
  if (!curve) return null;
  return (
    <CurveEditor curve={curve} applyLabel="Apply this curve" description="Both fans, for the current thermal profile."
      onApply={(c) => void mod.action("fan", "set_curve", { curve: c })} />
  );
}

function Fan({ m }: { m: ModuleStatus }) {
  const d = m.details;
  const live = useLive();
  const [edit, setEdit] = useState(false);
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Fans</DialogControlsSectionHeader>
      {d.fixedByOs ? (
        <ToggleField label="Pin the fan curve" checked={false} disabled description={m.message || "Not needed"}
          onChange={() => undefined} />
      ) : (
        <ModuleToggle m={m} label="Pin the fan curve"
          description="Stops both fans from getting stuck at full speed after sleep. Keeps each profile's curve."
          onChange={(on) => void mod.enable("fan", on)} />
      )}
      {isActive(m) && (
        <>
          <InfoField label="Thermal profile" value={live?.platformProfile ?? d.profile} />
          <InfoField label="Fans" value={live?.fansRpm.length ? `${live.fansRpm.map((r) => r ?? "–").join(" / ")} rpm` : null} />
          <InfoField label="CPU temperature" value={live?.cpu.tempC != null ? `${Math.round(live.cpu.tempC)} °C` : null} />
        </>
      )}
      {isActive(m) && m.enabled && !d.fixedByOs && (
        <>
          <ToggleField label="Edit the curve of this profile" checked={edit} onChange={setEdit} />
          {edit && <FanCurve m={m} />}
          <ButtonItem layout="below" onClick={() => void mod.action("fan", "restore_factory")}>
            Restore the factory curve for this profile
          </ButtonItem>
        </>
      )}
    </DialogControlsSection>
  );
}

/** One sample per day: battery health as a small line chart. */
function HealthHistory({ history }: { history: { d: string; h: number; e: number }[] }) {
  if (history.length === 0) return null;
  const first = history[0], last = history[history.length - 1];
  if (history.length < 2) return <InfoField label="Health history" value={`since ${first.d}: ${first.h} %`} />;
  const W = 600, H = 120, pad = 6;
  const hs = history.map((x) => x.h);
  const lo = Math.min(...hs) - 1, hi = Math.max(...hs) + 1;
  const pts = history.map((x, i) => `${pad + (i * (W - 2 * pad)) / (history.length - 1)},${pad + ((hi - x.h) * (H - 2 * pad)) / (hi - lo)}`);
  return (
    <FocusStop>
      <Field label="Health history" description={`${first.d}: ${first.h} % → ${last.d}: ${last.h} % (${history.length} days)`} />
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "120px" }}>
        <polyline points={pts.join(" ")} fill="none" stroke="#1a9fff" strokeWidth="2" />
      </svg>
    </FocusStop>
  );
}

function Battery({ m }: { m: ModuleStatus }) {
  const d = m.details;
  const b = useLive()?.battery;
  const power = batteryPower(b);
  const [limit, setLimit] = useState<number>(d.chargeLimit ?? 100);
  useEffect(() => setLimit(d.chargeLimit ?? 100), [d.chargeLimit]);
  const send = useDebounced((v: number) => void mod.action("battery", "set_charge_limit", { level: v >= 100 ? null : v }));
  if (!m.supported) return null;
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Battery</DialogControlsSectionHeader>
      <InfoField label="Charge" value={b?.capacity != null ? `${b.capacity} % · ${b.status}` : null} />
      <InfoField label="Health" value={d.healthPct != null ? `${d.healthPct} % (${d.energyFullWh} of ${d.energyDesignWh} Wh)` : null} />
      <InfoField label={power.label} value={power.value} />
      {d.chargeLimitSupported && (
        <SliderField label="Charge limit" value={limit} min={Math.max(50, d.chargeLimitMin ?? 50)} max={100} step={5} showValue
          valueSuffix=" %" description={limit >= 100 ? "No limit" : "Charging stops here. Same setting as in Steam's power settings."}
          onChange={(v) => { setLimit(v); send(v); }} />
      )}
      {d.chargeLimitSupported && (d.chargeLimit != null || d.fullOnce) && (
        <ButtonItem layout="below"
          description={d.fullOnce ? "Charging to 100 %; the limit comes back once the battery is full." : "Lifts the limit until the battery is full, then sets it again."}
          onClick={() => void mod.action("battery", d.fullOnce ? "cancel_full_once" : "charge_full_once")}>
          {d.fullOnce ? "Cancel the full charge" : "Charge to 100 % once"}
        </ButtonItem>
      )}
      {d.mcuPowersave !== null && (
        <ToggleField label="Controller power saving in sleep" checked={!!d.mcuPowersave}
          description="On: less drain in sleep, but the controller forgets vibration and lighting settings (this plugin re-sends them)."
          onChange={(on) => void mod.action("battery", "set_mcu_powersave", { on })} />
      )}
      {d.bootSound !== null && (
        <ToggleField label="Boot sound" checked={!!d.bootSound} onChange={(on) => void mod.action("battery", "set_boot_sound", { on })} />
      )}
      {d.pendingReboot && <InfoField label="Firmware setting changed" value="takes effect after a reboot" />}
      <HealthHistory history={d.history ?? []} />
    </DialogControlsSection>
  );
}

export function Power() {
  const cpu = useModule("cpu_boost");
  const fan = useModule("fan");
  const bat = useModule("battery");
  return (
    <DialogBody>
      {cpu && <CpuBoost m={cpu} />}
      {fan && <Fan m={fan} />}
      {bat && <Battery m={bat} />}
    </DialogBody>
  );
}
