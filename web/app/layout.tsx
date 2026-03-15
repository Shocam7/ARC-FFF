import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "ARC Meeting Room",
  description: "Join the ARC multi-agent meeting room from your browser."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

