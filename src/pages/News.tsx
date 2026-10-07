import { ButtonItem, DialogBody, DialogControlsSection, DialogControlsSectionHeader, Field, Navigation } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FocusStop } from "../components/FocusStop";
import { mod, useModule } from "../store";

const date = (d: number | string | null | undefined) =>
  typeof d === "number" ? (d ? new Date(d * 1000).toLocaleDateString() : "") : (d ?? "").replace(/\//g, "-");

const CHANNEL: Record<string, string> = { rel: "Stable", rc: "Stable (RC)", beta: "Beta", bc: "Beta (RC)", preview: "Preview", pc: "Preview (RC)", main: "Main" };

function Link({ url, label }: { url?: string | null; label: string }) {
  if (!url) return null;
  return <ButtonItem layout="below" onClick={() => Navigation.NavigateToExternalWeb(url)}>{label}</ButtonItem>;
}

export function News() {
  const m = useModule("news");
  const d = m?.details ?? {};
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    // opening the page marks everything seen; the badge in the panel goes away
    if (m && (d.unseen ?? []).length) void mod.action("news", "mark_seen");
  }, [m?.details.unseen?.length]);
  if (!m) return null;
  const items: any[] = d.items ?? [];
  const issues = items.filter((i) => i.kind === "issue");
  const steamos = items.filter((i) => i.kind === "steamos");
  const asus = items.filter((i) => i.kind === "bios" || i.kind === "firmware");
  const refresh = async () => {
    setBusy(true);
    try {
      await mod.action("news", "refresh");
    } finally {
      setBusy(false);
    }
  };
  const downloadBios = async () => {
    setBusy(true);
    try {
      const r = await mod.action("news", "download_bios");
      if (r.ok) {
        const res = r.result as { dir: string; files: string[] };
        toaster.toast({ title: "BIOS downloaded", body: `${res.dir}: ${res.files.join(", ")}` });
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <DialogBody>
      <DialogControlsSection>
        <ButtonItem layout="below" disabled={busy}
          description={`${d.fetchedAt ? `Updated ${new Date(d.fetchedAt * 1000).toLocaleString()}` : "Not fetched yet"}${d.error ? ` · ${d.error}` : ""}`}
          onClick={() => void refresh()}>
          Check now
        </ButtonItem>
      </DialogControlsSection>
      {issues.length > 0 && (
        <DialogControlsSection>
          <DialogControlsSectionHeader>Known issues</DialogControlsSectionHeader>
          {issues.map((i) => (
            <div key={i.id}>
              <Field focusable label={i.title} description={`${date(i.date)} · ${i.body ?? ""}`} />
              <Link url={i.url} label="Details" />
            </div>
          ))}
        </DialogControlsSection>
      )}
      <DialogControlsSection>
        <DialogControlsSectionHeader>{`SteamOS · ${(d.channel && CHANNEL[d.channel]) ?? d.channel ?? "?"} channel · installed ${d.installed?.steamos ?? "?"}`}</DialogControlsSectionHeader>
        {steamos.length === 0 && <Field focusable label="No release notes loaded" />}
        {steamos.map((i) => (
          <div key={i.id}>
            <Field focusable label={`${i.title}${i.newer ? " · new" : ""}`} description={date(i.date)} />
            {i.highlights?.length > 0 && (
              <FocusStop>
                <ul style={{ margin: "4px 0 8px 16px", padding: 0, fontSize: "13px" }}>
                  {i.highlights.map((h: string) => <li key={h}>{h}</li>)}
                </ul>
              </FocusStop>
            )}
            <Link url={i.url} label="Release notes" />
          </div>
        ))}
      </DialogControlsSection>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{`ASUS · BIOS installed ${d.installed?.bios ?? "?"}`}</DialogControlsSectionHeader>
        {asus.map((i) => (
          <Field key={i.id} focusable label={`${i.title} ${i.version}${i.newer ? " · new" : ""}`} description={`${date(i.date)} · ${i.size ?? ""}`} />
        ))}
        {asus.some((i) => i.kind === "bios") && (
          <ButtonItem layout="below" disabled={busy}
            description="Saves the EZ Flash file to ~/Downloads. Copy it to a FAT32 USB stick, then hold Volume Down while powering on and open EZ Flash in the BIOS."
            onClick={() => void downloadBios()}>
            Download the EZ Flash file
          </ButtonItem>
        )}
      </DialogControlsSection>
    </DialogBody>
  );
}
