// JSX typing for the <warden-orb> web component served from /public/warden/warden-orb.js.
import type { DetailedHTMLProps, HTMLAttributes } from "react";

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "warden-orb": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        mode?: "idle" | "listening" | "speaking" | "thinking";
        mood?: "calm" | "amber" | "stop";
      };
    }
  }
}
