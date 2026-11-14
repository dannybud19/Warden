import type { Metadata } from "next";
import { Inter } from "next/font/google";
import localFont from "next/font/local";
import { MotionProvider } from "@/components/warden/MotionProvider";
import { ProductChrome } from "@/components/warden/ProductChrome";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-inter",
});

// Aave's type system on a free font: General Sans (Fontshare, ITF Free Font License) as the
// stand-in for Aave Repro, which is proprietary. Variable, so the 450 step works.
const generalSans = localFont({
  src: "./fonts/GeneralSans-Variable.woff2",
  weight: "200 700",
  variable: "--font-general",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Warden",
  description: "Warden checks the homes you're renting for scams, and tells you what to ask before you pay.",
};

export default function ProductLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${generalSans.variable}`}>
      <body className="font-sans text-ink">
        <MotionProvider>
          <ProductChrome>{children}</ProductChrome>
        </MotionProvider>
      </body>
    </html>
  );
}
