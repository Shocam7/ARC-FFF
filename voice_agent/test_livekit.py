import os
import uuid
import sys

# Set dummy env vars for testing code validity
os.environ["LIVEKIT_API_KEY"] = "devkey"
os.environ["LIVEKIT_API_SECRET"] = "secret"

try:
    from livekit.api import AccessToken, VideoGrants
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)

LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
TOKEN_TTL_SECONDS = 3600

def test_token():
    room = "arc-room"
    identity = f"guest-{uuid.uuid4().hex[:8]}"
    
    try:
        grant = VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
        )

        token = (
            AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(identity)
            .with_grants(grant)
            .with_ttl(TOKEN_TTL_SECONDS)
            .to_jwt()
        )
        print("Token generated successfully!")
        print(token[:20] + "...")
    except Exception as e:
        print(f"Error generating token: {e}")

if __name__ == "__main__":
    test_token()
