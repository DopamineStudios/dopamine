from __future__ import annotations

from typing import Any


def _fmt_value(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    if value is None:
        lines.append(f"{pad}- *(empty)*")
    elif isinstance(value, bool):
        lines.append(f"{pad}- {'Yes' if value else 'No'}")
    elif isinstance(value, (int, float, str)):
        text = str(value).replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "…"
        lines.append(f"{pad}- {text}")
    elif isinstance(value, dict):
        if not value:
            lines.append(f"{pad}- *(no entries)*")
        else:
            for k, v in value.items():
                if isinstance(v, (dict, list)) and v:
                    lines.append(f"{pad}- **{k.replace('_', ' ').title()}:**")
                    lines.extend(_fmt_value(v, indent + 1))
                else:
                    lines.append(f"{pad}- **{k.replace('_', ' ').title()}:** {_scalar(v)}")
    elif isinstance(value, list):
        if not value:
            lines.append(f"{pad}- *(none)*")
        else:
            for i, item in enumerate(value, 1):
                if isinstance(item, dict):
                    lines.append(f"{pad}{i}.")
                    lines.extend(_fmt_value(item, indent + 1))
                else:
                    lines.append(f"{pad}{i}. {_scalar(item)}")
    else:
        lines.append(f"{pad}- {value!s}")
    return lines


def _scalar(value: Any) -> str:
    if value is None:
        return "*(empty)*"
    text = str(value).replace("\n", " ")
    return text[:200] + "…" if len(text) > 200 else text


def payload_to_markdown(payload: dict) -> str:
    meta = payload.get("export_meta", {})
    lines = [
        "# Dopamine Data Export",
        "",
        "This document is a human-readable summary of data stored by the Dopamine bot.",
        "",
        "## Export Information",
        "",
        f"- **Bot version:** {meta.get('bot_version', 'Unknown')}",
        f"- **Exported at:** {meta.get('exported_at', 'Unknown')}",
        f"- **Scope:** {meta.get('scope', 'Unknown')}",
    ]
    if meta.get("subject_user_id"):
        lines.append(f"- **User ID:** {meta['subject_user_id']}")
    if meta.get("guild_id"):
        lines.append(f"- **Server ID:** {meta['guild_id']}")
    if meta.get("guild_name"):
        lines.append(f"- **Server name:** {meta['guild_name']}")

    global_data = payload.get("global") or {}
    if global_data:
        lines.extend(["", "## Your Global Data", ""])
        lines.append("Data not tied to a specific server.")
        lines.append("")
        for feature_id, data in sorted(global_data.items()):
            lines.append(f"### {feature_id.replace('_', ' ').title()}")
            lines.extend(_fmt_value(data, 0))
            lines.append("")

    guilds = payload.get("guilds") or {}
    if guilds:
        lines.extend(["", "## Data by Server", ""])
        for gid, gdata in sorted(guilds.items(), key=lambda x: str(x[0])):
            name = gdata.get("guild_name") or f"Server {gid}"
            lines.append(f"### {name}")
            lines.append(f"- **Server ID:** {gid}")
            lines.append("")
            for feature_id, fdata in sorted(gdata.items()):
                if feature_id == "guild_name":
                    continue
                lines.append(f"#### {feature_id.replace('_', ' ').title()}")
                lines.extend(_fmt_value(fdata, 0))
                lines.append("")

    if not global_data and not guilds:
        lines.extend(["", "*No data was found for this export request.*", ""])

    lines.extend([
        "",
        "---",
        "",
        "*For the complete raw dataset, see `raw_dopamine_export.json` in this archive.*",
    ])
    return "\n".join(lines)
