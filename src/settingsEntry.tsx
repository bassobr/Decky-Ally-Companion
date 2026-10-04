/**
 * An "Ally Companion" entry in Steam's own settings menu.
 *
 * Steam's settings route renders a component that renders SidebarNavigation with a fresh `pages`
 * array ({visible, title, icon, route, content}); the patch wraps the components below the route
 * until it finds that array and appends an entry. The entry shows the status and a button that
 * opens the fullscreen view; it does not redirect by itself, so Back from the fullscreen view does
 * not bounce. Anything unexpected leaves Steam's menu as it is.
 */
import { routerHook } from "@decky/api";
import { ButtonItem, DialogBody, DialogControlsSection, Field, findInReactTree } from "@decky/ui";
import type { ReactNode } from "react";
import { FaGamepad } from "react-icons/fa";
import { openPage } from "./navigation";
import { warnings } from "./status";
import { usePluginState } from "./store";
import { t } from "./strings";

const SETTINGS = "/settings";
const ROUTE = "/settings/ally-companion";
const MAX_DEPTH = 4;

function Entry() {
  const s = usePluginState().state;
  const w = s ? warnings(s) : [];
  return (
    <DialogBody>
      <DialogControlsSection>
        <Field label={s?.device.model ?? t.title} description={w.length ? w.join(" · ") : t.allGood} />
        <ButtonItem layout="below" onClick={() => openPage("overview")}>Open Ally Companion</ButtonItem>
      </DialogControlsSection>
    </DialogBody>
  );
}

const wrapped = new Map<unknown, unknown>();

function inject(ret: any): boolean {
  const nav = findInReactTree(ret, (x: any) => Array.isArray(x?.pages) && x.pages.some((p: any) => p?.route?.startsWith?.(SETTINGS)));
  if (!nav) return false;
  if (!nav.pages.some((p: any) => p?.route === ROUTE)) {
    nav.pages.push("separator", { visible: true, title: t.title, icon: <FaGamepad />, route: ROUTE, content: <Entry /> });
  }
  return true;
}

function wrap(type: any, depth: number): any {
  if (typeof type !== "function") return type;
  if (wrapped.has(type)) return wrapped.get(type);
  const fn = function (this: unknown, ...args: unknown[]): ReactNode {
    const ret: any = type.apply(this, args);
    try {
      if (!inject(ret) && depth < MAX_DEPTH && ret?.type) return { ...ret, type: wrap(ret.type, depth + 1) };
    } catch (e) {
      console.warn("[Ally Companion] settings entry not added", e);
    }
    return ret;
  };
  wrapped.set(type, fn);
  return fn;
}

const patch = (props: any) => {
  const child = props.children;
  if (child?.type && !child.__allyCompanion) props.children = { ...child, type: wrap(child.type, 0), __allyCompanion: true };
  return props;
};

export function addSettingsEntry(): void {
  routerHook.addPatch(SETTINGS, patch);
}

export function removeSettingsEntry(): void {
  routerHook.removePatch(SETTINGS, patch);
}
