import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { MotionProvider } from "@/components/warden/MotionProvider";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Warden",
  description: "Warden checks the homes you're renting for scams, and tells you what to ask before you pay.",
};

export default function ProductLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans text-ink">
        <MotionProvider>{children}</MotionProvider>
      </body>
    </html>
  );
}
