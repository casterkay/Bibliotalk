import { NextResponse } from "next/server";

export async function forwardResponse(resp: Response): Promise<NextResponse> {
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const json = await resp.json();
    return NextResponse.json(json, { status: resp.status });
  }
  const text = await resp.text();
  return new NextResponse(text, { status: resp.status });
}
