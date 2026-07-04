"""
Contoso カスタマーサポート ポリシー MCP サーバー
=================================================
返品 / 配送 / 支払い / ポイント のポリシーを提供するリモート MCP サーバー。
Foundry エージェントの `mcp` ツールから呼び出される（Streamable-HTTP, パス /mcp）。

- トランスポート: streamable-http（FastMCP）
- 認証: なし（無認証エンドポイント）。ヘルスチェック（/）も無認証。
- データ: data/policies.json（決定的に返却 → 評価の安定化・groundedness 向上）

ローカル起動:
    pip install -r requirements.txt
    python server.py            # http://localhost:8000/mcp
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
_DATA_PATH = Path(__file__).parent / "data" / "policies.json"
with _DATA_PATH.open(encoding="utf-8") as f:
    POLICIES: dict[str, Any] = json.load(f)

# host/port は ACA / ローカル双方で利用
_HOST = os.environ.get("HOST", "0.0.0.0")
_PORT = int(os.environ.get("PORT", "8000"))

mcp = FastMCP("contoso-policy", host=_HOST, port=_PORT)


# 支払い方法の別名（英語・ローマ字・略称）→ 正式名称（policies.json のキー）
_PAYMENT_METHOD_ALIASES = {
    "クレジットカード": "クレジットカード",
    "クレカ": "クレジットカード",
    "credit_card": "クレジットカード",
    "creditcard": "クレジットカード",
    "credit card": "クレジットカード",
    "credit": "クレジットカード",
    "card": "クレジットカード",
    "デビットカード": "デビットカード",
    "デビット": "デビットカード",
    "debit_card": "デビットカード",
    "debitcard": "デビットカード",
    "debit card": "デビットカード",
    "debit": "デビットカード",
    "コンビニ支払い": "コンビニ支払い",
    "コンビニ": "コンビニ支払い",
    "convenience_store": "コンビニ支払い",
    "convenience store": "コンビニ支払い",
    "konbini": "コンビニ支払い",
    "銀行振込": "銀行振込",
    "振込": "銀行振込",
    "bank_transfer": "銀行振込",
    "bank transfer": "銀行振込",
    "電子マネー": "電子マネー",
    "e_money": "電子マネー",
    "emoney": "電子マネー",
    "electronic money": "電子マネー",
    "contoso ポイント": "Contoso ポイント",
    "contoso point": "Contoso ポイント",
    "contoso points": "Contoso ポイント",
    "point": "Contoso ポイント",
    "points": "Contoso ポイント",
    "ポイント": "Contoso ポイント",
}


def _normalize_payment_method(method: str) -> str:
    """支払い方法の入力を正式名称に正規化する。一致しなければ元の値を返す。"""
    key = (method or "").strip().lower()
    return _PAYMENT_METHOD_ALIASES.get(key, method)


# ---------------------------------------------------------------------------
# ツール定義（プロンプトの4ドメインに対応）
# ---------------------------------------------------------------------------
@mcp.tool()
def get_return_policy(category: str = "general", purchased_days_ago: Optional[int] = None) -> dict:
    """商品カテゴリと購入からの経過日数に基づき、Contoso の返品ポリシーを返します。

    category: general / digital / perishable / clearance のいずれか。
    purchased_days_ago: 購入からの経過日数（任意）。指定すると返金種別を判定します。
    """
    ret = POLICIES["returns"]
    cat_key = (category or "general").lower()
    cat = ret["categories"].get(cat_key, ret["categories"]["general"])

    result: dict[str, Any] = {
        "category": cat_key,
        "returnable": cat["returnable"],
        "window_days": ret["window_days"],
        "required": ret["required"],
        "note": cat["note"],
    }

    if not cat["returnable"]:
        result["refund_type"] = "対象外"
        result["summary"] = f"{cat['note']}（返品不可）"
        return result

    if purchased_days_ago is not None:
        within = purchased_days_ago <= ret["window_days"]
        refund = ret["within_window_refund"] if within else ret["after_window_refund"]
        refund_jp = "全額返金" if refund == "full_refund" else "店舗クレジット"
        result["within_window"] = within
        result["refund_type"] = refund_jp
        result["summary"] = (
            f"購入から{purchased_days_ago}日経過。"
            f"{ret['window_days']}日以内のため{refund_jp}が可能です。"
            if within
            else f"購入から{purchased_days_ago}日経過。"
            f"{ret['window_days']}日を超えているため{refund_jp}での対応となります。"
        )
    else:
        result["refund_type"] = "30日以内: 全額返金 / 超過後: 店舗クレジット"
        result["summary"] = (
            f"{ret['window_days']}日以内は全額返金、超過後は店舗クレジットでの対応です。"
        )
    return result


@mcp.tool()
def get_shipping_policy(destination: str = "domestic", order_amount: Optional[int] = None) -> dict:
    """配送先（国内/海外）と注文金額に基づき、配送可否・送料・目安日数を返します。

    destination: 'domestic'（国内）または 'international'（海外）。'日本'/'国内' 等も国内扱い。
    order_amount: 注文金額（円・任意）。指定すると送料無料判定を行います。
    """
    ship = POLICIES["shipping"]
    d = (destination or "domestic").lower()
    is_intl = any(k in d for k in ("intl", "international", "海外", "overseas", "abroad"))

    if is_intl:
        info = ship["international"]
        result: dict[str, Any] = {
            "destination": "international",
            "available": info["available"],
            "fee": info["base_fee"],
            "estimated_days": info["estimated_days"],
            "note": info["note"],
            "summary": (
                f"海外配送は可能です。基本送料は{info['base_fee']}円、"
                f"目安は{info['estimated_days']}です。{info['note']}"
            ),
        }
        return result

    info = ship["domestic"]
    result = {
        "destination": "domestic",
        "available": info["available"],
        "free_shipping_threshold": info["free_shipping_threshold"],
        "standard_fee": info["standard_fee"],
        "estimated_days": info["estimated_days"],
        "express_fee": info["express_fee"],
        "express_days": info["express_days"],
    }
    if order_amount is not None:
        free = order_amount >= info["free_shipping_threshold"]
        fee = 0 if free else info["standard_fee"]
        result["order_amount"] = order_amount
        result["is_free_shipping"] = free
        result["applied_fee"] = fee
        result["summary"] = (
            f"注文金額{order_amount}円は{info['free_shipping_threshold']}円以上のため送料無料です。"
            if free
            else f"注文金額{order_amount}円は{info['free_shipping_threshold']}円未満のため"
            f"送料{info['standard_fee']}円がかかります。"
        )
    else:
        result["summary"] = (
            f"国内配送は{info['free_shipping_threshold']}円以上で送料無料、"
            f"未満は{info['standard_fee']}円です。目安は{info['estimated_days']}です。"
        )
    return result


@mcp.tool()
def get_payment_policy(method: Optional[str] = None) -> dict:
    """利用可能な支払い方法、分割可否、返金処理日数を返します。

    method: 特定の支払い方法（任意）。指定するとその方法の詳細を返します。
        日本語の正式名称のほか、英語・ローマ字・略称（例: credit_card, creditcard,
        credit card, クレカ）も受け付けて正規化します。
    """
    pay = POLICIES["payment"]
    result: dict[str, Any] = {
        "methods": pay["methods"],
        "installments": pay["installments"],
        "note": pay["note"],
    }
    if method:
        canonical = _normalize_payment_method(method)
        refund = pay["refund_processing_days"].get(canonical)
        result["method"] = canonical
        result["supported"] = canonical in pay["methods"]
        result["refund_processing_days"] = refund
        if canonical in pay["methods"]:
            result["summary"] = (
                f"{canonical}はご利用いただけます。"
                + (f"返金処理は{refund}です。" if refund else "")
            )
        else:
            result["summary"] = f"{method}は現在対応していません。"
    else:
        result["refund_processing_days"] = pay["refund_processing_days"]
        result["summary"] = "利用可能な支払い方法: " + " / ".join(pay["methods"])
    return result


@mcp.tool()
def get_loyalty_points(customer_id: Optional[str] = None) -> dict:
    """Contoso ポイントの付与率・換算・有効期限を返します。customer_id 指定で残高を返します。

    customer_id: 顧客ID（任意, 例 'C-1001'）。指定すると保有ポイント残高を返します。
    """
    loy = POLICIES["loyalty"]
    result: dict[str, Any] = {
        "earn_rate": f"{loy['earn_rate_per_100_jpy']}ポイント / 100円",
        "redeem_value": f"1ポイント = {loy['redeem_value_jpy_per_point']}円",
        "expiry_months": loy["expiry_months"],
        "expiry_note": loy["expiry_note"],
        "tiers": loy["tiers"],
    }
    if customer_id:
        cust = loy["customers"].get(customer_id)
        if cust:
            result["customer_id"] = customer_id
            result["name"] = cust["name"]
            result["tier"] = cust["tier"]
            result["balance"] = cust["balance"]
            result["summary"] = (
                f"{cust['name']}様（{cust['tier']}）の保有ポイントは{cust['balance']}ポイントです。"
            )
        else:
            result["customer_id"] = customer_id
            result["found"] = False
            result["summary"] = f"顧客ID {customer_id} は見つかりませんでした。確認が必要です。"
    else:
        result["summary"] = (
            f"100円ごとに{loy['earn_rate_per_100_jpy']}ポイント付与、"
            f"1ポイント1円で利用可能。最終利用から{loy['expiry_months']}か月で失効します。"
        )
    return result


# ---------------------------------------------------------------------------
# ヘルスチェック
# ---------------------------------------------------------------------------
async def _health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def build_app():
    """Streamable-HTTP の Starlette アプリにヘルスルートを付与して返す（無認証）。"""
    app = mcp.streamable_http_app()
    app.add_route("/", _health, methods=["GET"])
    app.add_route("/healthz", _health, methods=["GET"])
    return app


# uvicorn から `server:app` として参照される ASGI アプリ
app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=_HOST, port=_PORT)
