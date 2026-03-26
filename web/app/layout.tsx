import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import AuthGuard from "@/components/AuthGuard";

export const metadata: Metadata = {
  title: "AutoScout AI",
  description: "Vehicle Deal Hunter",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body className="flex h-screen overflow-hidden bg-gray-50 font-sans antialiased">
        <AuthGuard>
          <Sidebar />
          {/* pb-16 reserves space for the mobile bottom tab bar */}
          <main className="flex-1 overflow-auto pb-16 md:pb-0">{children}</main>
        </AuthGuard>
      </body>
    </html>
  );
}
