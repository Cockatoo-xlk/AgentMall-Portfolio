"""Local entry only. No command creates a paid approval receipt."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from agentmall.infra.llm import AgentStopped
from agentmall.playground.app import create_live_app
from agentmall.playground.environment import initialize_environment, load_environment
from agentmall.playground.policy import (
    ROOT,
    PlaygroundPolicy,
    PlaygroundRejected,
    source_fingerprint,
    validate_approval,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--init-environment", action="store_true")
    parser.add_argument("--config", default=str(ROOT / ".playground/policy.json"))
    parser.add_argument("--approval", default=str(ROOT / ".playground/approval.json"))
    parser.add_argument("--enable-live", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    state = ROOT / ".playground"
    try:
        if args.host != "127.0.0.1" or not 1024 <= args.port <= 65535:
            raise PlaygroundRejected("LOCALHOST_REQUIRED")
        if args.describe:
            print(
                json.dumps(
                    {
                        "mode": "PLAN_ONLY",
                        "authorization": "NOT_GRANTED",
                        "source_sha256": source_fingerprint(),
                        "model_id": "deepseek-flash",
                        "price_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
                        "max_model_calls": 30,
                        "max_cost_cny": "5",
                        "max_wall_seconds": 1200,
                    }
                )
            )
            return 0
        if args.init_environment:
            if not Path("/.dockerenv").exists():
                raise PlaygroundRejected("OWNED_COMPOSE_ENVIRONMENT_REQUIRED")
            url = os.environ.get("AGENTMALL_PLAYGROUND_DATABASE_URL")
            if not url:
                raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED")
            _, ident = asyncio.run(initialize_environment(state, url))
            print(
                json.dumps(
                    {
                        "status": "OWNED_ENVIRONMENT_READY",
                        "environment_id": str(ident),
                        "paid_requests": 0,
                        "source_sha256": source_fingerprint(),
                    }
                )
            )
            return 0
        try:
            policy = PlaygroundPolicy.model_validate_json(Path(args.config).read_text())
        except Exception:
            raise PlaygroundRejected("POLICY_REQUIRED") from None
        if not args.enable_live:
            raise PlaygroundRejected("LIVE_DISABLED")
        validate_approval(policy, args.approval)
        settings, ident = load_environment(state)
        if ident != policy.environment_id:
            raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED")
        if args.check:
            print(
                json.dumps(
                    {
                        "status": "ADMISSION_CHECKED_NO_KEY_READ",
                        "authorization": "LOCAL_RECEIPT_VALIDATED",
                        "model_id": policy.model_id,
                        "paid_requests": 0,
                    }
                )
            )
            return 0
        # Never enable model callbacks or SDK debug logging in this local service.
        os.environ.pop("OPENAI_LOG", None)
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        app = create_live_app(
            policy, approval_path=args.approval, state_dir=state, settings=settings
        )
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")
        return 0
    except (PlaygroundRejected, AgentStopped) as exc:
        code = exc.code if isinstance(exc, AgentStopped) else str(exc)
        print(json.dumps({"status": "NO_GO", "code": code, "paid_requests": 0}))
        return 2
    except Exception:
        print(
            json.dumps({"status": "NO_GO", "code": "PLAYGROUND_STARTUP_FAILED", "paid_requests": 0})
        )
        return 2
