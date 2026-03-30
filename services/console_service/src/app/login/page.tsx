"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";

export default function LoginPage() {
  const [token, setToken] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <div className="rounded-lg border bg-white p-6 shadow-sm">
        <div className="mb-4">
          <div className="text-lg font-semibold">Admin Login</div>
          <div className="text-sm text-gray-600">Enter `BIBLIOTALK_ADMIN_TOKEN`.</div>
        </div>

        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setErr(null);
            try {
              await apiPost("/api/auth/login", { token });
              router.replace("/agents");
            } catch (e: any) {
              setErr(e?.detail || "Login failed");
            }
          }}
        >
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
            placeholder="Token"
            type="password"
            autoFocus
          />
          {err ? <div className="text-sm text-red-600">{err}</div> : null}
          <button className="w-full rounded bg-black px-3 py-2 text-sm text-white hover:bg-gray-800">
            Login
          </button>
        </form>
      </div>
    </div>
  );
}
