"""HTTP bearer verification for protected API routes."""

from __future__ import annotations

from fastapi import HTTPException, Request


class BearerChecker:
    """`Depends(BearerChecker(token))` on a router."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def __call__(self, request: Request) -> None:
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: send Authorization: Bearer <token> (see secrets/bearer.token under the server data directory).",
            )
        if auth[7:].strip() != self._token:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: bearer token does not match this server (reload TOKEN from the same MEMORYAGENT_DATA_DIR the server uses).",
            )
