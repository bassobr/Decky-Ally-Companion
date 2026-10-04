import { Navigation } from "@decky/ui";

export const ROUTE = "/ally-companion";

export function openPage(page = "overview"): void {
  Navigation.Navigate(`${ROUTE}/${page}`);
  Navigation.CloseSideMenus();
}
