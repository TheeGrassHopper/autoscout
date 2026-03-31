"use client";

import { useSession } from "next-auth/react";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"];

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "loading") return;
    if (!PUBLIC_PATHS.includes(pathname) && status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, pathname, router]);

  // Public pages always render immediately
  if (PUBLIC_PATHS.includes(pathname)) return <>{children}</>;

  // Wait for session check before rendering protected content
  if (status === "loading") return null;
  if (status === "unauthenticated") return null;

  return <>{children}</>;
}
