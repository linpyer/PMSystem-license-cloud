from __future__ import annotations

from typing import Any


IMPORTANT_REASON_OPTIONS: tuple[tuple[str, str], ...] = (
    ("after_sale_dispute", "售后争议"),
    ("merchant_intercept", "商家自行拦截"),
    ("platform_intercept_back", "平台拦截退回"),
    ("user_rejected", "用户拒收"),
    ("other", "其他"),
)
IMPORTANT_REASON_LABELS = dict(IMPORTANT_REASON_OPTIONS)
IMPORTANT_REASON_TYPES = set(IMPORTANT_REASON_LABELS)
NON_DEAL_IMPORTANT_REASON_TYPES = {
    "merchant_intercept",
    "platform_intercept_back",
    "user_rejected",
}
DEFAULT_IMPORTANT_REASON_TYPE = "after_sale_dispute"


def normalize_important_reason_type(value: Any, is_important: bool = False) -> str:
    reason_type = str(value or "").strip()
    if reason_type in IMPORTANT_REASON_TYPES:
        return reason_type
    return "other" if is_important else ""


def important_reason_label(reason_type: Any, custom_reason: Any = "", legacy_note: Any = "") -> str:
    normalized = normalize_important_reason_type(reason_type, bool(reason_type or legacy_note or custom_reason))
    custom = str(custom_reason or "").strip()
    note = str(legacy_note or "").strip()
    if normalized == "other":
        detail = custom or note
        return f"其他：{detail}" if detail else "其他"
    if normalized:
        return IMPORTANT_REASON_LABELS.get(normalized, "其他")
    if note:
        return f"其他：{note}"
    return ""


def important_note_from_reason(reason_type: Any, custom_reason: Any = "") -> str:
    normalized = normalize_important_reason_type(reason_type, True)
    custom = str(custom_reason or "").strip()
    if normalized == "other":
        return custom or "其他"
    return IMPORTANT_REASON_LABELS.get(normalized, "")


def is_important_entry(entry: dict[str, Any]) -> bool:
    return bool(
        entry.get("is_important")
        or str(entry.get("important_reason_type") or "").strip()
        or str(entry.get("important_reason_custom") or "").strip()
        or str(entry.get("important_note") or "").strip()
        or str(entry.get("important_at") or "").strip()
    )


def important_reason_text(entry: dict[str, Any]) -> str:
    is_important = bool(
        entry.get("is_important")
        or str(entry.get("important_note") or "").strip()
        or str(entry.get("important_at") or "").strip()
    )
    reason_type = normalize_important_reason_type(entry.get("important_reason_type"), is_important)
    return important_reason_label(
        reason_type,
        entry.get("important_reason_custom"),
        entry.get("important_note"),
    )


def remark_display_parts(entry: dict[str, Any]) -> tuple[str, str, str, bool]:
    remark = str(entry.get("remark") or "").strip()
    important = is_important_entry(entry)
    reason_text = important_reason_text(entry)
    if important and remark:
        display_text = f"重要｜{reason_text}｜{remark}" if reason_text else f"重要｜{remark}"
    elif important:
        display_text = f"重要｜{reason_text}" if reason_text else "重要"
    elif remark:
        display_text = remark
    else:
        display_text = "点击添加备注"

    tooltip_parts: list[str] = []
    if important:
        tooltip_parts.append("重要或有争议的单号")
        if reason_text:
            tooltip_parts.append(f"重要原因：{reason_text}")
    if remark:
        tooltip_parts.append(f"备注：{remark}" if important else remark)
    tooltip = "\n".join(tooltip_parts) if tooltip_parts else "点击添加备注"
    return display_text, tooltip, remark, important
