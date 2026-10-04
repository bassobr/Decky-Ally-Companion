import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, Field, Navigation } from "@decky/ui";
import { toaster } from "@decky/api";
import { useState } from "react";
import { checkForUpdate, getDiagnostics, installUpdate } from "../backend";
import { FocusStop } from "../components/FocusStop";
import { t } from "../strings";
import type { PluginState } from "../types";

const REPO_URL = "https://github.com/bassobr/Decky-Ally-Companion";
const BLOCK_LINES = 14;

function blocks(text: string): string[] {
  const lines = text.split("\n");
  const out: string[] = [];
  for (let i = 0; i < lines.length; i += BLOCK_LINES) out.push(lines.slice(i, i + BLOCK_LINES).join("\n"));
  return out;
}

export function System({ state, refresh }: { state: PluginState; refresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const u = state.update;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toaster.toast({ title: t.title, body: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBody>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{t.version}</DialogControlsSectionHeader>
        <Field label={t.title} focusable>{state.version}</Field>
        {u.updateAvailable && u.latestVersion ? (
          <ButtonItem layout="below" disabled={busy} onClick={() => void run(installUpdate)}>
            {t.updateTo(u.latestVersion)}
          </ButtonItem>
        ) : (
          <ButtonItem layout="below" disabled={busy} description={u.error ? `${t.updateFailed}: ${u.error}` : t.upToDate}
            onClick={() => void run(async () => { await checkForUpdate(true); await refresh(); })}>
            {t.checkUpdate}
          </ButtonItem>
        )}
        <ButtonItem layout="below" description={REPO_URL} onClick={() => Navigation.NavigateToExternalWeb(REPO_URL)}>
          {t.source}
        </ButtonItem>
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{t.diagnostics}</DialogControlsSectionHeader>
        <ButtonItem layout="below" disabled={busy} description={report ? t.reportSaved : undefined}
          onClick={() => void run(async () => setReport((await getDiagnostics()).text))}>
          {t.createReport}
        </ButtonItem>
        {report && blocks(report).map((b, i) => (
          <FocusStop key={i}>
            <pre style={{ margin: 0, fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{b}</pre>
          </FocusStop>
        ))}
      </DialogControlsSection>
    </DialogBody>
  );
}
