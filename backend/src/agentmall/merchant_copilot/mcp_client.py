"""Optional official MCP client read adapter; existing Gateway/auth stay unchanged."""

from fastapi.encoders import jsonable_encoder

from agentmall.identity.service import require_merchant
from agentmall.mcp_gateway.domain import read_domain


class MerchantMCPReader:
    def __init__(self, client):
        # Client transport/credential is supplied by a trusted composition root, never model args.
        self.client = client

    async def read(self, app, session, actor, name, args):
        require_merchant(actor)
        if name not in {"list_merchant_catalog", "list_merchant_after_sales"}:
            raise ValueError("MCP_READ_TOOL_NOT_ALLOWED")
        authoritative = await read_domain(app, session, actor, name, args)
        result = await self.client.call_tool(name, args.model_dump(mode="json"))
        wire = result.structured_content
        if (
            result.is_error
            or not isinstance(wire, dict)
            or not wire.get("ok")
            or wire.get("data") != jsonable_encoder(authoritative)
        ):
            raise ValueError("MCP_IDENTITY_OR_DATA_MISMATCH")
        return authoritative
