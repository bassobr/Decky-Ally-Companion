import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, SliderField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { InfoField, isActive, ModuleToggle } from "../components/ModuleRow";
import { useDebounced } from "../hooks/useDebounced";
import { mod, useModule } from "../store";
import type { ModuleStatus } from "../types";

const pct = (pwm: number) => Math.round((pwm * 100) / 255);
const pwm = (p: number) => Math.round((p * 255) / 100);

function CpuBoost({ m }: { m: ModuleStatus }) {
  const d = m.details;
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>CPU</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Keep CPU boost off"
        description="Cooler and quieter. The firmware drops the frequency cap on every charger plug; this re-sends it."
        onChange={(on) => void mod.enable("cpu_boost", on)} />
      {isActive(m) && m.enabled && (
        <>
          <ToggleField label="Re-send the cap on charger events" checked={!!d.refreshOnCharger}
            onChange={(on) => void mod.options("cpu_boost", { refreshOnCharger: on })} />
          <InfoField label="Cores above the cap" value={`${d.overCapCores ?? "–"} of ${d.policies ?? "–"}`} />
          <ButtonItem layout="below" description={d.lastKick ? `Last: ${d.lastKick} (${d.kicks} total)` : undefined}
            onClick={() => void mod.action("cpu_boost", "refresh_now")}>
            Re-send the cap now
          </ButtonItem>
        </>
      )}
    </DialogControlsSection>
  );
}

function FanCurve({ m }: { m: ModuleStatus }) {
  const curve = m.details.curve as { temps: number[]; pwm1: number[]; pwm2: number[] } | null;
  const [duty, setDuty] = useState<number[]>([]);
  useEffect(() => {
    if (curve) setDuty(curve.pwm1.map((v, i) => pct(Math.max(v, curve.pwm2[i]))));
  }, [JSON.stringify(curve)]);
  if (!curve || duty.length !== 8) return null;
  const apply = () => void mod.action("fan", "set_curve", {
    curve: { temps: curve.temps, pwm1: duty.map(pwm), pwm2: duty.map(pwm) },
  });
  return (
    <>
      {curve.temps.map((t, i) => (
        <SliderField key={i} label={`At ${t} °C`} value={duty[i]} min={0} max={100} step={1} showValue valueSuffix=" %"
          onChange={(v) => setDuty(duty.map((x, j) => (j === i ? v : j > i ? Math.max(x, v) : Math.min(x, v))))} />
      ))}
      <ButtonItem layout="below" description="Both fans, for the current thermal profile." onClick={apply}>
        Apply this curve
      </ButtonItem>
    </>
  );
}

function Fan({ m }: { m: ModuleStatus }) {
  const d = m.details;
  const [edit, setEdit] = useState(false);
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Fans</DialogControlsSectionHeader>
      <ModuleToggle m={m} label="Pin the fan curve"
        description="Stops both fans from getting stuck at full speed after sleep. Keeps each profile's curve."
        onChange={(on) => void mod.enable("fan", on)} />
      {isActive(m) && (
        <>
          <InfoField label="Thermal profile" value={d.profile} />
          <InfoField label="Fans" value={d.rpm ? `${d.rpm[0] ?? "–"} / ${d.rpm[1] ?? "–"} rpm` : null} />
          <InfoField label="CPU temperature" value={d.temp != null ? `${Math.round(d.temp)} °C` : null} />
        </>
      )}
      {isActive(m) && m.enabled && (
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

function Battery({ m }: { m: ModuleStatus }) {
  const d = m.details;
  const [limit, setLimit] = useState<number>(d.chargeLimit ?? 100);
  useEffect(() => setLimit(d.chargeLimit ?? 100), [d.chargeLimit]);
  const send = useDebounced((v: number) => void mod.action("battery", "set_charge_limit", { level: v >= 100 ? null : v }));
  if (!m.supported) return null;
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Battery</DialogControlsSectionHeader>
      <InfoField label="Charge" value={d.capacity != null ? `${d.capacity} % · ${d.status}` : null} />
      <InfoField label="Health" value={d.healthPct != null ? `${d.healthPct} % (${d.energyFullWh} of ${d.energyDesignWh} Wh)` : null} />
      <InfoField label="Power draw" value={d.powerW != null ? `${d.powerW} W` : null} />
      {d.chargeLimitSupported && (
        <SliderField label="Charge limit" value={limit} min={Math.max(50, d.chargeLimitMin ?? 50)} max={100} step={5} showValue
          valueSuffix=" %" description={limit >= 100 ? "No limit" : "Charging stops here. Same setting as in Steam's power settings."}
          onChange={(v) => { setLimit(v); send(v); }} />
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
