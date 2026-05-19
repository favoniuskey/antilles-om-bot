"""Validation syntaxique de v2_target.json.

Importable sans discord.py installé — utilisé par `migrate_v2.py --validate-target`
pour valider le fichier cible avant toute exécution réseau.
"""

from __future__ import annotations

import json
from pathlib import Path


TARGET_FILE = Path(__file__).parent / "v2_target.json"


_PERM_ALIASES = {"read_messages": "view_channel"}


VALID_PERMISSIONS: frozenset[str] = frozenset({
    "create_instant_invite", "kick_members", "ban_members", "administrator",
    "manage_channels", "manage_guild", "add_reactions", "view_audit_log",
    "priority_speaker", "stream", "view_channel", "read_messages",
    "send_messages", "send_tts_messages", "manage_messages", "embed_links",
    "attach_files", "read_message_history", "mention_everyone",
    "external_emojis", "use_external_emojis", "view_guild_insights",
    "connect", "speak", "mute_members", "deafen_members", "move_members",
    "use_voice_activation", "change_nickname", "manage_nicknames",
    "manage_roles", "manage_permissions", "manage_webhooks",
    "manage_expressions", "manage_emojis", "manage_emojis_and_stickers",
    "use_application_commands", "use_slash_commands", "request_to_speak",
    "manage_events", "manage_threads", "create_public_threads",
    "create_private_threads", "external_stickers", "use_external_stickers",
    "send_messages_in_threads", "use_embedded_activities",
    "start_embedded_activities", "moderate_members",
    "view_creator_monetization_analytics", "use_soundboard",
    "create_expressions", "create_events", "use_external_sounds",
    "send_voice_messages", "send_polls", "use_external_apps",
})


def _norm(p: str) -> str:
    return _PERM_ALIASES.get(p, p)


def load_target(path: Path = TARGET_FILE) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_target(target: dict) -> list[str]:
    """Retourne une liste d'erreurs (vide si OK)."""
    errors: list[str] = []

    meta = target.get("_metadata", {})
    if not meta.get("guild_id"):
        errors.append("_metadata.guild_id manquant")

    role_names: set[str] = set()
    for i, role in enumerate(target.get("roles", [])):
        name = role.get("name")
        if not name:
            errors.append(f"roles[{i}] : champ 'name' manquant")
            continue
        if name in role_names:
            errors.append(f"roles[{i}] : nom dupliqué `{name}`")
        role_names.add(name)

        origin = role.get("_origin", "existing")
        if origin not in ("existing", "new", "rename"):
            errors.append(f"roles[{i}] (`{name}`) : _origin invalide `{origin}`")
        if origin == "rename" and not role.get("old_name"):
            errors.append(f"roles[{i}] (`{name}`) : rename sans old_name")
        if origin == "existing" and not role.get("existing_id") and not role.get("_protected"):
            errors.append(f"roles[{i}] (`{name}`) : existing sans existing_id")

        for p in role.get("permissions", []):
            if _norm(p) not in VALID_PERMISSIONS:
                errors.append(f"roles[{i}] (`{name}`) : permission inconnue `{p}`")

    cat_names: set[str] = set()
    for i, cat in enumerate(target.get("categories", [])):
        name = cat.get("name")
        if not name:
            errors.append(f"categories[{i}] : champ 'name' manquant")
            continue
        if name in cat_names:
            errors.append(f"categories[{i}] : nom dupliqué `{name}`")
        cat_names.add(name)

        for role_ref in cat.get("overrides", {}).keys():
            if role_ref not in role_names and role_ref != "@everyone":
                errors.append(
                    f"categories[{i}] (`{name}`) : override référence rôle inconnu `{role_ref}`"
                )

        for j, ch in enumerate(cat.get("channels", [])):
            if not ch.get("name"):
                errors.append(f"categories[{i}].channels[{j}] : nom manquant")
            ch_type = ch.get("type", "text")
            if ch_type not in ("text", "voice"):
                errors.append(
                    f"categories[{i}].channels[{j}] (`{ch.get('name')}`) : type invalide `{ch_type}`"
                )
            for ow_role in ch.get("overrides", {}).keys():
                if ow_role not in role_names and ow_role != "@everyone":
                    errors.append(
                        f"categories[{i}].channels[{j}] (`{ch.get('name')}`) : "
                        f"override référence rôle inconnu `{ow_role}`"
                    )
            for ow_spec in ch.get("overrides", {}).values():
                for p in ow_spec.get("allow", []) + ow_spec.get("deny", []):
                    if _norm(p) not in VALID_PERMISSIONS:
                        errors.append(
                            f"categories[{i}].channels[{j}] (`{ch.get('name')}`) : "
                            f"permission inconnue `{p}`"
                        )

        for ow_spec in cat.get("overrides", {}).values():
            for p in ow_spec.get("allow", []) + ow_spec.get("deny", []):
                if _norm(p) not in VALID_PERMISSIONS:
                    errors.append(
                        f"categories[{i}] (`{name}`) : permission inconnue `{p}`"
                    )

    return errors


def stats(target: dict) -> dict:
    return {
        "roles": len(target.get("roles", [])),
        "categories": len(target.get("categories", [])),
        "channels": sum(len(c.get("channels", [])) for c in target.get("categories", [])),
    }
