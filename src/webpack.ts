/**
 * Steam's webpack module registry, for the Steam-side patches (layoutPatch.ts, controllerArt.ts).
 *
 * Lookups go through the modules Steam has loaded already (`r.c`). Only when none of them has what
 * we look for are the factories that mention it run, which is what Steam would do on first use but
 * earlier; so a module's start-up code runs out of order only as a last resort.
 */
let req: any;

export function webpackRequire(): any {
  if (!req) (window as any).webpackChunksteamui?.push([[Math.random()], {}, (r: any) => { req = r; }]);
  return req;
}

type Hit = { value: any; moduleId: string };

function scan(r: any, ids: string[], load: boolean, pick: (value: any, key: string) => boolean): Hit | null {
  for (const id of ids) {
    let exp: any;
    try { exp = load ? r(id) : r.c[id].exports; } catch { continue; }
    if (!exp || typeof exp !== "object") continue;
    for (const k of Object.keys(exp)) {
      let v: any;
      try { v = exp[k]; } catch { continue; }
      if (v != null && pick(v, k)) return { value: v, moduleId: id };
    }
  }
  return null;
}

/** The first export of a module whose source mentions `needle` that `pick` accepts. */
export function findExport(r: any, needle: string, pick: (value: any, key: string) => boolean): Hit | null {
  const ids = Object.keys(r.m).filter((id) => {
    try { return String(r.m[id]).includes(needle); } catch { return false; }
  });
  const loaded = (id: string) => !!r.c?.[id];
  return scan(r, ids.filter(loaded), false, pick) ?? scan(r, ids.filter((id) => !loaded(id)), true, pick);
}
