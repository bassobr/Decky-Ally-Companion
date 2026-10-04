import { DialogBody, Field, SidebarNavigation, type SidebarNavigationPage } from "@decky/ui";
import type { ReactNode } from "react";
import { FaBatteryHalf, FaCog, FaGamepad, FaInfoCircle, FaLightbulb, FaListUl, FaNewspaper, FaVolumeUp } from "react-icons/fa";
import { ROUTE } from "../navigation";
import { usePluginState } from "../store";
import { t } from "../strings";
import { Controller } from "./Controller";
import { Lighting } from "./Lighting";
import { Overview } from "./Overview";
import { Planned } from "./Planned";
import { Power } from "./Power";
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

  const page = (identifier: string, title: string, icon: ReactNode, content: ReactNode): SidebarNavigationPage =>
    ({ identifier, title, icon, route: `${ROUTE}/${identifier}`, content });
  const planned = (identifier: string, title: string, icon: ReactNode) => page(identifier, title, icon, <Planned page={identifier} />);

  const pages: (SidebarNavigationPage | "separator")[] = [
    page("overview", t.overview, <FaInfoCircle />, <Overview state={state} />),
    "separator",
    planned("audio", t.audio, <FaVolumeUp />),
    page("controller", t.controller, <FaGamepad />, <Controller />),
    page("lighting", t.lighting, <FaLightbulb />, <Lighting />),
    page("power", t.power, <FaBatteryHalf />, <Power />),
    planned("profiles", t.profiles, <FaListUl />),
    planned("news", t.news, <FaNewspaper />),
    "separator",
    page("system", t.system, <FaCog />, <System state={state} refresh={refresh} />),
  ];

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title={t.title} showTitle pages={pages} />
    </div>
  );
}
