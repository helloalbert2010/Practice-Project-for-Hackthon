from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from campus_alerts.config import AppConfig


URGENCY_SCORES = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

CHINESE_URGENCY_MAP = {
    "低": "low",
    "一般": "medium",
    "中": "medium",
    "中等": "medium",
    "高": "high",
    "严重": "high",
    "紧急": "critical",
    "危急": "critical",
    "特别紧急": "critical",
}

CATEGORY_KEYWORDS = [
    ("消防火情", ["火灾", "着火", "浓烟", "烟雾", "爆炸", "消防", "燃气", "煤气"]),
    ("医疗急救", ["受伤", "流血", "昏迷", "晕倒", "心脏", "中毒", "急救", "救护", "过敏"]),
    ("安全治安", ["打架", "斗殴", "持刀", "威胁", "盗窃", "抢劫", "骚扰", "尾随", "入侵"]),
    ("心理危机", ["自杀", "轻生", "崩溃", "抑郁", "恐慌", "伤害自己"]),
    ("设施故障", ["停电", "漏水", "断电", "电梯", "塌陷", "破损", "故障", "危险设施"]),
    ("交通出行", ["车祸", "撞车", "拥堵", "校车", "交通", "摔车"]),
]

CRITICAL_KEYWORDS = [
    "爆炸",
    "持刀",
    "持枪",
    "昏迷",
    "自杀",
    "轻生",
    "坠楼",
    "大量流血",
    "火灾",
]

HIGH_KEYWORDS = [
    "打架",
    "斗殴",
    "受伤",
    "流血",
    "浓烟",
    "煤气",
    "燃气",
    "中毒",
    "骚扰",
    "尾随",
    "电梯困人",
]

LOW_KEYWORDS = ["遗失", "丢失", "噪音", "轻微", "咨询", "报修"]

VALID_CATEGORIES = [
    "消防火情",
    "医疗急救",
    "安全治安",
    "心理危机",
    "设施故障",
    "交通出行",
    "其他",
]

SYSTEM_PROMPT = """
你是校园安全事件分级引擎。请根据上报信息做分类和紧急度评估。

必须只输出一个 JSON 对象，不要输出 Markdown、解释、思考过程或额外文本。
JSON 字段固定为：
- type: 只能从 消防火情、医疗急救、安全治安、心理危机、设施故障、交通出行、其他 中选择
- urgency: 只能是 low、medium、high、critical
- urgency_score: 只能是 1、2、3、4，且 low=1、medium=2、high=3、critical=4
- reason: 一句话中文理由

分级规则：
- 出现火灾、明显浓烟、爆炸、燃气泄漏、持刀、昏迷、坠楼、自杀/轻生、大量流血时，urgency 必须是 critical。
- 出现打架、受伤、流血、骚扰尾随、电梯困人、中毒、严重设施危险时，urgency 至少是 high。
- 无立即人身风险的一般报修、噪音、遗失物品可评为 low。
- 信息不足但可能影响安全时，评为 medium，不要评为 low。
""".strip()


def assess_event(event_payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    if config.deepseek_api_key:
        try:
            return _call_deepseek(event_payload, config)
        except (error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
            fallback = heuristic_assessment(event_payload)
            fallback["source"] = "heuristic_after_deepseek_error"
            fallback["reason"] = f"{fallback['reason']} DeepSeek 调用失败，已使用本地规则。"
            fallback["debug_error"] = exc.__class__.__name__
            return fallback

    return heuristic_assessment(event_payload)


def _call_deepseek(event_payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    prompt = {
        "reported_type": event_payload["type"],
        "description": event_payload["description"],
        "occurred_at": event_payload["occurred_at"],
        "location": event_payload["location"],
    }
    body = {
        "model": config.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        "thinking": {"type": config.deepseek_thinking_type},
        "reasoning_effort": config.deepseek_reasoning_effort,
        "stream": False,
    }
    encoded_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    http_request = request.Request(
        config.deepseek_api_url,
        data=encoded_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.deepseek_api_key}",
            "Content-Type": "application/json",
        },
    )

    with request.urlopen(http_request, timeout=config.deepseek_timeout_seconds) as response:
        response_body = response.read().decode("utf-8")

    api_payload = json.loads(response_body)
    content = api_payload["choices"][0]["message"]["content"]
    parsed_content = _parse_json_content(content)
    assessment = normalize_assessment(parsed_content, event_payload)
    assessment["source"] = "deepseek"
    return assessment


def _parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


def normalize_assessment(raw: dict[str, Any], event_payload: dict[str, Any]) -> dict[str, Any]:
    raw_event_type = (
        raw.get("type")
        or raw.get("category")
        or raw.get("事件类型")
        or infer_category(event_payload)
    )
    urgency = normalize_urgency(raw.get("urgency") or raw.get("紧急度"))
    urgency_score = raw.get("urgency_score") or raw.get("score") or raw.get("紧急度分数")

    if urgency_score is None:
        urgency_score = URGENCY_SCORES[urgency]
    else:
        urgency_score = max(1, min(4, int(urgency_score)))
        urgency = urgency_from_score(urgency_score)

    assessment = {
        "type": normalize_category(str(raw_event_type), event_payload),
        "urgency": urgency,
        "urgency_score": urgency_score,
        "reason": str(raw.get("reason") or raw.get("理由") or "DeepSeek 已完成分类与紧急度评估。"),
        "source": "deepseek",
    }
    return apply_local_safety_floor(assessment, event_payload)


def normalize_category(value: str, event_payload: dict[str, Any]) -> str:
    cleaned_value = value.strip()
    if cleaned_value in VALID_CATEGORIES:
        return cleaned_value
    return infer_category(event_payload)


def apply_local_safety_floor(
    assessment: dict[str, Any], event_payload: dict[str, Any]
) -> dict[str, Any]:
    local_assessment = heuristic_assessment(event_payload)
    if local_assessment["urgency_score"] <= assessment["urgency_score"]:
        return assessment

    assessment = assessment.copy()
    assessment["urgency"] = local_assessment["urgency"]
    assessment["urgency_score"] = local_assessment["urgency_score"]
    if assessment["type"] == "其他" and local_assessment["type"] != "其他":
        assessment["type"] = local_assessment["type"]
    assessment["reason"] = f"{assessment['reason']} 已根据本地安全规则上调紧急度。"
    return assessment


def normalize_urgency(value: Any) -> str:
    if value is None:
        return "medium"

    text = str(value).strip().lower()
    if text in URGENCY_SCORES:
        return text

    return CHINESE_URGENCY_MAP.get(str(value).strip(), "medium")


def urgency_from_score(score: int) -> str:
    if score >= 4:
        return "critical"
    if score == 3:
        return "high"
    if score == 2:
        return "medium"
    return "low"


def heuristic_assessment(event_payload: dict[str, Any]) -> dict[str, Any]:
    text = f"{event_payload.get('type', '')} {event_payload.get('description', '')} {event_payload.get('location', '')}"
    category = infer_category(event_payload)

    if any(keyword in text for keyword in CRITICAL_KEYWORDS):
        urgency = "critical"
        reason = "描述中包含可能危及生命或快速扩散的关键词。"
    elif any(keyword in text for keyword in HIGH_KEYWORDS):
        urgency = "high"
        reason = "描述中包含安全、医疗或人身风险相关关键词。"
    elif any(keyword in text for keyword in LOW_KEYWORDS):
        urgency = "low"
        reason = "描述更接近低风险事务或一般报修。"
    else:
        urgency = "medium"
        reason = "未发现极端风险关键词，按中等紧急度处理。"

    return {
        "type": category,
        "urgency": urgency,
        "urgency_score": URGENCY_SCORES[urgency],
        "reason": reason,
        "source": "heuristic",
    }


def infer_category(event_payload: dict[str, Any]) -> str:
    text = f"{event_payload.get('type', '')} {event_payload.get('description', '')}"
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category

    reported_type = str(event_payload.get("type") or "").strip()
    if reported_type and reported_type != "其他":
        return reported_type
    return "其他"
