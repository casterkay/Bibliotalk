import { NextResponse, type NextRequest } from "next/server";

const ADMIN_COOKIE_NAME = "bt_admin_token";

function expectedAdminToken(): string {
  const token = (process.env.BIBLIOTALK_ADMIN_TOKEN || "").trim();
  if (!token) {
    throw new Error("Missing BIBLIOTALK_ADMIN_TOKEN");
  }
  return token;
}

export function isAuthenticated(request: NextRequest): boolean {
  const expected = expectedAdminToken();
  const supplied = (request.cookies.get(ADMIN_COOKIE_NAME)?.value || "").trim();
  return Boolean(supplied && supplied === expected);
}

export function requireAuthenticated(request: NextRequest): NextResponse | null {
  if (isAuthenticated(request)) return null;
  return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
}

export function setAdminCookie(response: NextResponse, token: string): void {
  response.cookies.set({
    name: ADMIN_COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
}

export function clearAdminCookie(response: NextResponse): void {
  response.cookies.set({
    name: ADMIN_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    expires: new Date(0),
  });
}
