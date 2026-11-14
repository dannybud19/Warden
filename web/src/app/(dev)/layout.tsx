import type { Metadata } from "next";
import { USE_MOCK } from "@/lib/config";
import "./dev.css";

export const metadata: Metadata = {
  title: "Rental Scam Shield (dev)",
  description: "Dev shell for testing the Rental Scam Shield flow",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header>
          Rental Scam Shield (dev shell)
          {USE_MOCK && <span className="tag">MOCK</span>}
        </header>
        {children}
      </body>
    </html>
  );
}
