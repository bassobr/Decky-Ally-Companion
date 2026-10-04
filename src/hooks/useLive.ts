import { useEffect, useState } from "react";
import { getLive } from "../backend";
import type { LiveValues } from "../types";

const POLL_MS = 2000;

/** Sensor values, polled only while the component using them is on screen. */
export function useLive(): LiveValues | null {
  const [live, setLive] = useState<LiveValues | null>(null);
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const v = await getLive();
        if (!stop) setLive(v);
      } catch {
        /* keep the last values */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, []);
  return live;
}

/** power_now is the charging power while charging and the draw while discharging. */
export function batteryPower(b: LiveValues["battery"] | undefined): { label: string; value: string | null } {
  const w = b?.powerW;
  if (b?.status === "Charging") return { label: "Charging power", value: w != null ? `${w} W` : null };
  if (b?.status === "Discharging") return { label: "Power draw", value: w != null ? `${w} W` : null };
  return { label: "Power", value: w ? `${w} W` : b?.status ?? null };
}
