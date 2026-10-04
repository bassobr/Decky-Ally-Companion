import { DialogBody, Field, SidebarNavigation, type SidebarNavigationPage } from "@decky/ui";
import { type ReactNode, useEffect } from "react";
import { FaBatteryHalf, FaCog, FaGamepad, FaInfoCircle, FaLightbulb, FaListUl, FaNewspaper, FaVolumeUp } from "react-icons/fa";
import { ROUTE } from "../navigation";
import { store, usePluginState } from "../store";
import { t } from "../strings";
import { Audio } from "./Audio";
import { Controller } from "./Controller";
import { Lighting } from "./Lighting";
import { News } from "./News";
import { Overview } from "./Overview";
import { Power } from "./Power";
import { Profiles } from "./Profiles";
import { System } from "./System";

/** A page fetches the plugin state when it opens; module details are otherwise only pushed on changes. */
function Fresh({ children }: { children: ReactNode }) {
  useEffect(() => void store.refresh(), []);
  return <>{children}</>;
}

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
    ({ identifier, title, icon, route: `${ROUTE}/${identifier}`, content: <Fresh>{content}</Fresh> });

  // No "separator" entries: with them Steam's SidebarNavigation moves the focus two items per D-pad
  // press and shows the page one behind the focus.
  const pages: SidebarNavigationPage[] = [
    page("overview", t.overview, <FaInfoCircle />, <Overview state={state} />),
    page("audio", t.audio, <FaVolumeUp />, <Audio />),
    page("controller", t.controller, <FaGamepad />, <Controller />),
    page("lighting", t.lighting, <FaLightbulb />, <Lighting />),
    page("power", t.power, <FaBatteryHalf />, <Power />),
    page("profiles", t.profiles, <FaListUl />, <Profiles />),
    page("news", t.news, <FaNewspaper />, <News />),
    page("system", t.system, <FaCog />, <System state={state} refresh={refresh} />),
  ];

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title={t.title} showTitle pages={pages} />
    </div>
  );
}
