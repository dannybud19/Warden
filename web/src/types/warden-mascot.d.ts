// JSX typing for the <warden-mascot> web component served from /public/warden/warden-mascot.js.
import type { DetailedHTMLProps, HTMLAttributes } from "react";

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "warden-mascot": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        state?: string;
        assets?: string;
      };
    }
  }
}
