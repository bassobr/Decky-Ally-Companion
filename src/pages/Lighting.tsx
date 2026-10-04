import { ButtonItem, ColorPickerModal, DialogBody, DialogControlsSection, DialogControlsSectionHeader, DropdownItem, showModal, SliderField } from "@decky/ui";
import { useEffect, useState } from "react";
import { isActive, ModuleToggle } from "../components/ModuleRow";
import { useDebounced } from "../hooks/useDebounced";
import { mod, useModule } from "../store";

const MODES = [
  { data: "static", label: "Static" },
  { data: "breathing", label: "Breathing" },
  { data: "cycle", label: "Colour cycle" },
  { data: "rainbow", label: "Rainbow" },
  { data: "battery", label: "Battery level" },
  { data: "off", label: "Off" },
];
const SPEEDS = [
  { data: "low", label: "Slow" },
  { data: "medium", label: "Medium" },
  { data: "high", label: "Fast" },
];

/** "hsla(h, s%, l%, a)" from the colour picker -> "#rrggbb". */
export function hslToHex(hsl: string): string | null {
  const m = hsl.match(/hsla?\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%/);
  if (!m) return null;
  const h = Number(m[1]) / 360, s = Number(m[2]) / 100, l = Number(m[3]) / 100;
  const f = (n: number) => {
    const k = (n + h * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    const c = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(c * 255).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function hexToHsl(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, Math.round(l * 100)];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [Math.round(h * 60), Math.round(s * 100), Math.round(l * 100)];
}

function pickColor(title: string, current: string, onPick: (hex: string) => void) {
  const [h, s, l] = hexToHsl(current);
  showModal(
    <ColorPickerModal closeModal={() => {}} title={title} defaultH={h} defaultS={s} defaultL={l} defaultA={1}
      onConfirm={(hsl: string) => {
        const hex = hslToHex(hsl);
        if (hex) onPick(hex);
      }} />,
  );
}

function Swatch({ color }: { color: string }) {
  return <span style={{ display: "inline-block", width: 28, height: 18, borderRadius: 4, background: color, border: "1px solid #fff4" }} />;
}

export function Lighting() {
  const m = useModule("lighting");
  const d = m?.details ?? {};
  const [brightness, setBrightness] = useState<number>(d.brightness ?? 60);
  useEffect(() => setBrightness(d.brightness ?? 60), [d.brightness]);
  const sendBrightness = useDebounced((v: number) => void mod.options("lighting", { brightness: v }));
  if (!m) return null;
  const on = m.enabled && isActive(m);
  const mode = d.mode ?? "static";
  return (
    <DialogBody>
      <DialogControlsSection>
        <DialogControlsSectionHeader>Joystick rings</DialogControlsSectionHeader>
        <ModuleToggle m={m} label="Control the lighting" description="Off: the rings keep whatever was set last."
          onChange={(v) => void mod.enable("lighting", v)} />
        {on && (
          <>
            <DropdownItem label="Mode" rgOptions={MODES} selectedOption={mode}
              onChange={(o) => void mod.options("lighting", { mode: o.data })} />
            {["static", "breathing", "cycle"].includes(mode) && (
              <ButtonItem layout="inline" label="Colour" onClick={() => pickColor("Colour", d.color, (c) => void mod.options("lighting", { color: c }))}>
                <Swatch color={d.color} />
              </ButtonItem>
            )}
            {mode === "breathing" && (
              <ButtonItem layout="inline" label="Second colour" description="Black: fade to dark"
                onClick={() => pickColor("Second colour", d.color2, (c) => void mod.options("lighting", { color2: c }))}>
                <Swatch color={d.color2} />
              </ButtonItem>
            )}
            {["breathing", "cycle", "rainbow"].includes(mode) && (
              <DropdownItem label="Speed" rgOptions={SPEEDS} selectedOption={d.speed}
                onChange={(o) => void mod.options("lighting", { speed: o.data })} />
            )}
            {mode !== "off" && (
              <SliderField label="Brightness" value={brightness} min={0} max={100} step={5} showValue valueSuffix=" %"
                description={mode === "static" ? undefined : "Effects know four levels only."}
                onChange={(v) => { setBrightness(v); sendBrightness(v); }} />
            )}
          </>
        )}
      </DialogControlsSection>
    </DialogBody>
  );
}
