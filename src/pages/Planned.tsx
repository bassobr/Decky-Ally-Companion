import { DialogBody, DialogControlsSection, DialogControlsSectionHeader, Field } from "@decky/ui";
import { plannedPages, t } from "../strings";

export function Planned({ page }: { page: string }) {
  return (
    <DialogBody>
      <DialogControlsSection>
        <DialogControlsSectionHeader>{t.planned}</DialogControlsSectionHeader>
        {(plannedPages[page] ?? []).map((line) => <Field key={line} label={line} focusable />)}
      </DialogControlsSection>
    </DialogBody>
  );
}
