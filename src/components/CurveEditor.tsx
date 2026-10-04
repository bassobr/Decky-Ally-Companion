import { ButtonItem, SliderField } from "@decky/ui";
import { useEffect, useState } from "react";

export type Curve = { temps: number[]; pwm1: number[]; pwm2: number[] };

const pct = (pwm: number) => Math.round((pwm * 100) / 255);
const pwm = (p: number) => Math.round((p * 255) / 100);

/** Eight duty points (both fans) over the curve's temperatures; points never go down with temperature. */
export function CurveEditor({ curve, applyLabel, description, onApply }: {
  curve: Curve;
  applyLabel: string;
  description?: string;
  onApply: (curve: Curve) => void;
}) {
  const [duty, setDuty] = useState<number[]>([]);
  useEffect(() => setDuty(curve.pwm1.map((v, i) => pct(Math.max(v, curve.pwm2[i])))), [JSON.stringify(curve)]);
  if (duty.length !== curve.temps.length) return null;
  return (
    <>
      {curve.temps.map((t, i) => (
        <SliderField key={i} label={`At ${t} °C`} value={duty[i]} min={0} max={100} step={1} showValue valueSuffix=" %"
          onChange={(v) => setDuty(duty.map((x, j) => (j === i ? v : j > i ? Math.max(x, v) : Math.min(x, v))))} />
      ))}
      <ButtonItem layout="below" description={description}
        onClick={() => onApply({ temps: curve.temps, pwm1: duty.map(pwm), pwm2: duty.map(pwm) })}>
        {applyLabel}
      </ButtonItem>
    </>
  );
}
