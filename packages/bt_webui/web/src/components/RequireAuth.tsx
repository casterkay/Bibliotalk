"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiGet } from "@/lib/api";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiGet<{ authenticated: boolean }>("/api/auth/whoami")
      .then((res) => {
        if (cancelled) return;
        if (!res.authenticated && pathname !== "/login") router.replace("/login");
        else setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router, pathname]);

  if (!ready) return null;
  return <>{children}</>;
}
