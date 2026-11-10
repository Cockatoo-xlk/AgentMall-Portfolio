"""Repeatable synthetic demo seed: insert missing business keys, never overwrite data."""

import argparse
import asyncio
from uuid import uuid5

from argon2 import PasswordHasher
from sqlalchemy.dialects.postgresql import insert

from agentmall.catalog.models import Product
from agentmall.catalog.profiles import CatalogProfile, expanded_products
from agentmall.identity.models import User
from agentmall.infra.config import Settings
from agentmall.infra.db import database

DEMO_PASSWORD = "AgentMall-demo-2026!"
PRODUCTS = [
    ("宿舍静音 K68", "keyboard", 19900, "静音轴", "有线", "68键", "较安静"),
    ("静音 K87", "keyboard", 29900, "静音轴", "双模", "87键", "较安静"),
    ("静音 K98", "keyboard", 39900, "静音轴", "三模", "98键", "较安静"),
    ("静音 K104", "keyboard", 49900, "静音轴", "有线", "104键", "较安静"),
    ("进阶 K75", "keyboard", 59900, "线性轴", "三模", "75键", "适中"),
    ("轻巧 K61", "keyboard", 15900, "线性轴", "有线", "61键", "适中"),
    ("段落 K87", "keyboard", 25900, "段落轴", "有线", "87键", "明显"),
    ("办公 K108", "keyboard", 35900, "静音轴", "双模", "108键", "较安静"),
    ("轻量鼠标 M1", "mouse", 9900, "无", "有线", "中号", "适中"),
    ("无线鼠标 M2", "mouse", 18900, "无", "无线", "中号", "较安静"),
    ("有线耳机 H1", "headphones", 12900, "无", "有线", "头戴", "不适用"),
    ("无线耳机 H2", "headphones", 32900, "无", "无线", "头戴", "不适用"),
]


async def seed(session, settings: Settings, *, profile: CatalogProfile = "legacy"):
    if profile not in {"legacy", "expanded"}:
        raise ValueError("Unknown catalogue profile")
    additions = expanded_products() if profile == "expanded" else ()
    password_hash = await asyncio.to_thread(PasswordHasher().hash, DEMO_PASSWORD)
    for login, role in [("buyer1", "buyer"), ("buyer2", "buyer"), ("merchant", "merchant")]:
        await session.execute(
            insert(User)
            .values(
                id=uuid5(settings.storefront_id, login),
                login=login,
                password_hash=password_hash,
                role=role,
                store_id=settings.storefront_id if role == "merchant" else None,
            )
            .on_conflict_do_nothing(index_elements=["login"])
        )
    for index, (name, category, price, switch, connection, size, noise) in enumerate(PRODUCTS):
        await session.execute(
            insert(Product)
            .values(
                id=uuid5(settings.storefront_id, f"synthetic-sku-{index + 1:02}"),
                store_id=settings.storefront_id,
                name=name,
                category=category,
                price_cents=price,
                on_hand=20,
                reserved=0,
                active=True,
                catalog_version=1,
                attributes={
                    "switch": switch,
                    "connection": connection,
                    # Explicit synthetic capabilities, without Bluetooth/2.4GHz claims.
                    "connection_capabilities": (
                        ["wired", "wireless"]
                        if connection in {"双模", "三模"}
                        else ["wireless"]
                        if connection == "无线"
                        else ["wired"]
                    ),
                    "size": size,
                    "noise": noise,
                },
                description="自建合成演示商品，不对应真实品牌。噪声为定性标签，不代表绝对无声。",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

    for product in additions:
        values = product.model_dump(exclude={"sku"})
        await session.execute(
            insert(Product)
            .values(
                id=uuid5(settings.storefront_id, "expanded-120-v1:" + product.sku),
                store_id=settings.storefront_id,
                reserved=0,
                active=True,
                catalog_version=1,
                **values,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )


async def main(profile: CatalogProfile = "legacy"):
    settings = Settings()
    engine, sessions = database(settings)
    try:
        async with sessions.begin() as session:
            await seed(session, settings, profile=profile)
        print("Synthetic seed committed; existing rows preserved.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("legacy", "expanded"), default="legacy")
    asyncio.run(main(parser.parse_args().profile))
