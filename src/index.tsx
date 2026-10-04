import { definePlugin, routerHook } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaGamepad } from "react-icons/fa";
import { QuickAccess } from "./components/QuickAccess";
import { ROUTE } from "./navigation";
import { Fullscreen } from "./pages/Fullscreen";
import { t } from "./strings";

export default definePlugin(() => {
  // Not exact: SidebarNavigation keeps the current page in the path below ROUTE.
  routerHook.addRoute(ROUTE, Fullscreen);
  return {
    name: t.title,
    titleView: <div className={staticClasses.Title}>{t.title}</div>,
    content: <QuickAccess />,
    icon: <FaGamepad />,
    onDismount() {
      routerHook.removeRoute(ROUTE);
    },
  };
});
