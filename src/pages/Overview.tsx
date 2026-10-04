import { DialogBody, DialogControlsSection, DialogControlsSectionHeader, Field } from "@decky/ui";
import { warnings } from "../status";
import { t } from "../strings";
import type { PluginState } from "../types";

const have = (ok: boolean) => (ok ? t.available : t.missing);

export function Overview({ state }: { state: PluginState }) {
  const { device: d, stack: s } = state;
  const w = warnings(state);
  const modules = Object.values(state.modules);
  return (
    <DialogBody>
      {w.length > 0 && (
        <DialogControlsSection>
          {w.map((text) => <Field key={text} label={text} focusable />)}
        </DialogControlsSection>
      )}
      <DialogControlsSection>
        <DialogControlsSectionHeader>{t.device}</DialogControlsSectionHeader>
        <Field label={t.model} focusable>{d.model ? `${d.model} (${d.board})` : `${t.unsupported} (${d.board || "?"})`}</Field>
        <Field label={t.bios} focusable>{d.bios || "?"}</Field>
        <Field label={t.mcu} focusable>{d.mcu ?? t.notReported}</Field>
        <Field label={t.os} focusable>{[d.os, d.osVersion, d.osBuild && `(${d.osBuild})`].filter(Boolean).join(" ")}</Field>
        <Field label={t.kernel} focusable>{d.kernel}</Field>
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{t.services}</DialogControlsSectionHeader>
        <Field label={t.inputplumber} focusable>{s.inputplumber.version ?? t.notRunning}</Field>
        <Field label={t.steamosManager} focusable>{s.steamosManager.deviceModel?.join(" / ") ?? t.notRunning}</Field>
        <Field label={t.allyDriver} focusable>{have(s.hidAsusAlly)}</Field>
        <Field label={t.ledRing} focusable>{have(s.led)}</Field>
        <Field label={t.armoury} focusable>{have(s.asusArmoury)}</Field>
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{t.modules}</DialogControlsSectionHeader>
        {modules.length === 0 && <Field label={t.noModules} focusable />}
        {modules.map((m) => (
          <Field key={m.id} label={m.title} focusable
            description={!m.supported ? `${t.notSupported}: ${m.reason}` : m.error ?? undefined} />
        ))}
      </DialogControlsSection>
    </DialogBody>
  );
}
