import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, Field, Navigation } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { backupSettings, checkForUpdate, getDiagnostics, installUpdate, listBackups, restoreBackup } from "../backend";
import { confirm } from "../steamRestart";
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

function Backups({ run, busy }: { run: (fn: () => Promise<unknown>) => Promise<void>; busy: boolean }) {
  const [list, setList] = useState<{ dir: string; backups: { name: string }[] } | null>(null);
  const load = async () => setList(await listBackups());
  useEffect(() => void load(), []);
  const label = (name: string) => name.replace(/^ally-companion-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.json$/, "$1-$2-$3 $4:$5:$6");
  const restore = async (name: string) => {
    if (!(await confirm("Restore settings", `Replace all settings with the backup from ${label(name)}?`, "Restore"))) return;
    await run(async () => {
      await restoreBackup(name);
      toaster.toast({ title: t.title, body: "Settings restored" });
    });
  };
  return (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Backup</DialogControlsSectionHeader>
      <ButtonItem layout="below" disabled={busy} description={list ? `Saved to ${list.dir}` : undefined}
        onClick={() => void run(async () => {
          const r = await backupSettings();
          toaster.toast({ title: t.title, body: `Backed up: ${r.name}` });
          await load();
        })}>
        Back up all settings
      </ButtonItem>
      {(list?.backups ?? []).slice(0, 8).map((b) => (
        <ButtonItem key={b.name} layout="inline" label={label(b.name)} disabled={busy} onClick={() => void restore(b.name)}>
          Restore
        </ButtonItem>
      ))}
    </DialogControlsSection>
  );
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
      <Backups run={run} busy={busy} />
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
