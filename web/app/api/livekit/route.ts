import { AccessToken } from "livekit-server-sdk";
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const room = req.nextUrl.searchParams.get("room") || "bidi-demo-room";
  const username = req.nextUrl.searchParams.get("username") || `guest-${Math.floor(Math.random() * 10000)}`;

  if (!process.env.NEXT_PUBLIC_LIVEKIT_API_KEY || !process.env.NEXT_PUBLIC_LIVEKIT_API_SECRET) {
    return NextResponse.json(
      { error: "Server misconfigured. Missing LiveKit keys." },
      { status: 500 }
    );
  }

  const at = new AccessToken(
    process.env.NEXT_PUBLIC_LIVEKIT_API_KEY,
    process.env.NEXT_PUBLIC_LIVEKIT_API_SECRET,
    {
      identity: username,
      // Token expires in 2 hours
      ttl: "2h",
    }
  );

  at.addGrant({
    roomJoin: true,
    room: room,
    canPublish: true,
    canSubscribe: true,
  });

  return NextResponse.json({ token: await at.toJwt() });
}
