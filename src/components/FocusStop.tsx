import { Focusable } from "@decky/ui";
import { type CSSProperties, type ReactNode, useRef } from "react";

/** A focus stop for content that is not a control; it scrolls into view when it gets focus. */
export function FocusStop({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <Focusable ref={ref} style={style} onActivate={() => {}}
      onGamepadFocus={() => ref.current?.scrollIntoView({ block: "nearest" })}>
      {children}
    </Focusable>
  );
}
