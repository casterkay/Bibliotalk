"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";

export function TopNav() {
  const router = useRouter();
  return (
    <div className="border-b bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-4 text-sm">
          <Link href="/agents" className="font-semibold">
            Bibliotalk Admin
          </Link>
          <Link href="/agents" className="text-gray-700 hover:underline">
            Agents
          </Link>
          <Link href="/collector" className="text-gray-700 hover:underline">
            Collector
          </Link>
          <Link href="/emos" className="text-gray-700 hover:underline">
            EverMemOS
          </Link>
        </div>
        <button
          className="rounded border px-3 py-1 text-sm hover:bg-gray-50"
          onClick={async () => {
            await apiPost("/api/auth/logout", {});
            router.replace("/login");
          }}
        >
          Logout
        </button>
      </div>
    </div>
  );
}
