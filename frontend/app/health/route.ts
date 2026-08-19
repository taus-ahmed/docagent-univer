import { NextResponse } from "next/server";

/**
 * Railway healthcheck endpoint.
 *
 * Railway waits for a 200 here before switching traffic to a new deployment,
 * so a container that builds but cannot serve is caught instead of going live.
 * Deliberately does no work and touches no backend: it answers whether THIS
 * service is up, and nothing else. A healthcheck that depends on another
 * service turns that service's outage into a failed deploy here.
 */
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok", service: "docagent-frontend" });
}
