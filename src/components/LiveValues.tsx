import { DialogControlsSection, DialogControlsSectionHeader } from "@decky/ui";
import { useEffect, useState } from "react";
import { getLive } from "../backend";
import { usePluginState } from "../store";
import type { LiveValues as Live } from "../types";
import { InfoField } from "./ModuleRow";

const POLL_MS = 2000;
const n = (v: number | null | undefined, unit: string) => (v == null ? null : `${v} ${unit}`);

/** Sensors, polled only while this section is on screen. */
export function LiveValues() {
  const [live, setLive] = useState<Live | null>(null);
  const boostModule = usePluginState().state?.modules.cpu_boost;
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
  if (!live) return null;
  const c = live.cpu, g = live.gpu;
  const fixOn = !!boostModule?.enabled || boostModule?.details.override === true;
  const boostText = c.boost
    ? "on"
    : `off${fixOn ? " (kept off by Ally Companion" + (boostModule?.details.override != null ? ", game profile" : "") + ")" : ""}`;
  return (
    <>
      <DialogControlsSection>
        <DialogControlsSectionHeader>Live</DialogControlsSectionHeader>
        <InfoField label="CPU" value={[n(c.tempC, "°C"), c.avgMHz != null ? `avg ${c.avgMHz} MHz, max ${c.maxMHz} MHz` : null].filter(Boolean).join(" · ")} />
        <InfoField label="GPU" value={[n(g.tempC, "°C"), n(g.clockMHz, "MHz"), g.busyPct != null ? `${g.busyPct} % busy` : null].filter(Boolean).join(" · ")} />
        <InfoField label="APU power" value={n(g.apuW, "W")} />
        <InfoField label="Battery" value={[live.battery.capacity != null ? `${live.battery.capacity} %` : null, live.battery.status,
          n(live.battery.powerW, "W")].filter(Boolean).join(" · ")} />
        <InfoField label="Fans" value={live.fansRpm.length ? live.fansRpm.map((r) => r ?? "–").join(" / ") + " rpm" : null} />
        <InfoField label="Power profile" value={[live.platformProfile, live.pptW[0] != null ? `PPT ${live.pptW.filter((x) => x != null).join("/")} W` : null].filter(Boolean).join(" · ")} />
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>CPU boost</DialogControlsSectionHeader>
        <InfoField label="Boost" value={boostText} />
        <InfoField label="Frequency cap" value={c.capMHz != null ? `${c.capMHz} MHz${c.hwMaxMHz && c.hwMaxMHz !== c.capMHz ? ` (hardware max ${c.hwMaxMHz} MHz)` : ""}` : null} />
        <InfoField label="Cores above the cap" value={`${c.overCap} of ${c.cores}`} />
        {boostModule?.details.lastKick && (
          <InfoField label="Cap last re-sent" value={`${boostModule.details.lastKick} (${boostModule.details.kicks} since start)`} />
        )}
      </DialogControlsSection>
    </>
  );
}
