import { definePlugin, routerHook } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaGamepad } from "react-icons/fa";
import { startAppWatcher, stopAppWatcher } from "./appWatcher";
import { QuickAccess, selectCurrentPanel } from "./components/QuickAccess";
import { stopLayoutPatch, syncLayoutPatch } from "./layoutPatch";
import { ROUTE } from "./navigation";
import { addSettingsEntry, removeSettingsEntry } from "./settingsEntry";
import { Fullscreen } from "./pages/Fullscreen";
import { connectEvents, disconnectEvents, store } from "./store";
import { t } from "./strings";

export default definePlugin(() => {
  // Not exact: SidebarNavigation keeps the current page in the path below ROUTE.
  routerHook.addRoute(ROUTE, Fullscreen);
  // The UI half of the gamepad layout module lives in Steam's process: follow the switch.
  const unsubscribe = store.subscribe(() => void syncLayoutPatch());
  connectEvents();
  startAppWatcher();
  addSettingsEntry();
  // after an update: once Decky has this bundle in its list (it loads a fresh install twice, ~2 s apart)
  const reselect = window.setTimeout(selectCurrentPanel, 3000);
  return {
    name: t.title,
    titleView: <div className={staticClasses.Title}>{t.title}</div>,
    content: <QuickAccess />,
    icon: <FaGamepad />,
    onDismount() {
      window.clearTimeout(reselect);
      unsubscribe();
      removeSettingsEntry();
      stopAppWatcher();
      stopLayoutPatch();
      disconnectEvents();
      routerHook.removeRoute(ROUTE);
    },
  };
});
