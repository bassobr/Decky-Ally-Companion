import { DialogBody, Field, SidebarNavigation, type SidebarNavigationPage } from "@decky/ui";
import type { ReactNode } from "react";
import { FaBatteryHalf, FaCog, FaGamepad, FaInfoCircle, FaLightbulb, FaListUl, FaNewspaper, FaVolumeUp } from "react-icons/fa";
import { usePluginState } from "../hooks/usePluginState";
import { ROUTE } from "../navigation";
import { t } from "../strings";
import { Overview } from "./Overview";
import { Planned } from "./Planned";
import { System } from "./System";

/** Everything beyond the sidebar essentials, laid out like Steam's own settings. */
export function Fullscreen() {
  const { state, error, refresh } = usePluginState();

  if (!state) {
    return (
      <div style={{ marginTop: "40px" }}>
        <DialogBody>
          <Field label={error ? t.backendError : t.title} description={error ?? undefined} />
        </DialogBody>
      </div>
    );
  }

  const planned = (identifier: string, title: string, icon: ReactNode): SidebarNavigationPage =>
    ({ identifier, title, icon, route: `${ROUTE}/${identifier}`, content: <Planned page={identifier} /> });

  const pages: (SidebarNavigationPage | "separator")[] = [
    { identifier: "overview", title: t.overview, icon: <FaInfoCircle />, route: `${ROUTE}/overview`, content: <Overview state={state} /> },
    "separator",
    planned("audio", t.audio, <FaVolumeUp />),
    planned("controller", t.controller, <FaGamepad />),
    planned("lighting", t.lighting, <FaLightbulb />),
    planned("power", t.power, <FaBatteryHalf />),
    planned("profiles", t.profiles, <FaListUl />),
    planned("news", t.news, <FaNewspaper />),
    "separator",
    { identifier: "system", title: t.system, icon: <FaCog />, route: `${ROUTE}/system`, content: <System state={state} refresh={refresh} /> },
  ];

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title={t.title} showTitle pages={pages} />
    </div>
  );
}
