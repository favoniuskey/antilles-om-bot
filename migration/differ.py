"""Comparateur état réel ↔ cible V2.

Lit l'état actuel du serveur Discord et le compare au `v2_target.json`,
produit une structure `Diff` consommée par `applier.py` (apply) ou
`reporter.py` (dry-run).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import discord


TARGET_FILE = Path(__file__).parent / "v2_target.json"


# Permissions textuelles qui n'existent pas comme attributs Permissions/Overwrite
# dans discord.py — à filtrer pour éviter AttributeError. read_messages est
# l'alias historique de view_channel.
_PERM_ALIASES = {"read_messages": "view_channel"}


# Set statique des permissions valides discord.py 2.x — utilisé par la
# validation sans dépendance à l'import discord (le validator est appelable
# depuis un environnement sans discord.py installé).
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
    "send_messages_in_threads", "use_embedded_activities", "start_embedded_activities",
    "moderate_members", "view_creator_monetization_analytics",
    "use_soundboard", "create_expressions", "create_events",
    "use_external_sounds", "send_voice_messages", "send_polls",
    "use_external_apps",
})


def _normalize_perm(name: str) -> str:
    return _PERM_ALIASES.get(name, name)


@dataclass
class RoleAction:
    kind: str  # "create" | "rename" | "update_perms" | "skip" | "flag" | "archive"
    target_name: str
    target_data: dict = field(default_factory=dict)
    current_role: Optional[discord.Role] = None
    reason: str = ""


@dataclass
class ChannelAction:
    kind: str  # "create" | "move" | "rename" | "archive" | "skip"
    target_name: str
    parent_category_name: str = ""
    target_data: dict = field(default_factory=dict)
    current_channel: Optional[discord.abc.GuildChannel] = None
    reason: str = ""


@dataclass
class CategoryAction:
    kind: str  # "create" | "rename" | "update_overrides" | "skip"
    target_name: str
    target_data: dict = field(default_factory=dict)
    current_category: Optional[discord.CategoryChannel] = None
    channel_actions: list[ChannelAction] = field(default_factory=list)
    reason: str = ""


@dataclass
class Diff:
    target: dict
    role_actions: list[RoleAction] = field(default_factory=list)
    category_actions: list[CategoryAction] = field(default_factory=list)
    orphan_channels: list[discord.abc.GuildChannel] = field(default_factory=list)
    orphan_categories: list[discord.CategoryChannel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_target(path: Path = TARGET_FILE) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_role(guild: discord.Guild, target_role: dict) -> Optional[discord.Role]:
    """Match par ID d'abord, fallback sur nom."""
    rid = target_role.get("existing_id")
    if rid:
        role = guild.get_role(int(rid))
        if role:
            return role
    # Pour les rôles "rename", chercher d'abord par old_name
    old_name = target_role.get("old_name")
    if old_name:
        for r in guild.roles:
            if r.name == old_name:
                return r
    name = target_role.get("name", "")
    for r in guild.roles:
        if r.name == name:
            return r
    return None


def _find_category(guild: discord.Guild, target_cat: dict) -> Optional[discord.CategoryChannel]:
    cid = target_cat.get("existing_id")
    if cid:
        cat = guild.get_channel(int(cid))
        if isinstance(cat, discord.CategoryChannel):
            return cat
    old_name = target_cat.get("old_name")
    if old_name:
        for c in guild.categories:
            if c.name == old_name:
                return c
    name = target_cat.get("name", "")
    for c in guild.categories:
        if c.name == name:
            return c
    return None


def _find_channel_in_guild(guild: discord.Guild, name: str) -> Optional[discord.abc.GuildChannel]:
    """Cherche un salon par nom (texte ou voix) anywhere dans le serveur."""
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        if ch.name == name:
            return ch
    return None


def _diff_role(guild: discord.Guild, target_role: dict, warnings: list[str]) -> RoleAction:
    name = target_role.get("name", "?")
    origin = target_role.get("_origin", "existing")
    protected = target_role.get("_protected", False)

    if protected:
        existing = _find_role(guild, target_role)
        if existing is None:
            warnings.append(f"Rôle protégé `{name}` introuvable sur le serveur (id `{target_role.get('existing_id')}`).")
        return RoleAction(kind="skip", target_name=name, target_data=target_role,
                          current_role=existing, reason="protected (bot-managed ou exception V2)")

    block = target_role.get("_block", "")
    if block == "À arbitrer":
        existing = _find_role(guild, target_role)
        return RoleAction(kind="flag", target_name=name, target_data=target_role,
                          current_role=existing,
                          reason=target_role.get("_note", "à valider manuellement"))

    if origin == "new":
        existing = _find_role(guild, target_role)
        if existing:
            return RoleAction(kind="update_perms", target_name=name, target_data=target_role,
                              current_role=existing, reason="rôle 'new' déjà présent — mise à jour des perms")
        return RoleAction(kind="create", target_name=name, target_data=target_role,
                          reason="rôle V2 à créer")

    if origin == "rename":
        existing = _find_role(guild, target_role)
        if existing is None:
            warnings.append(f"Rôle à renommer `{target_role.get('old_name')}` → `{name}` introuvable.")
            return RoleAction(kind="create", target_name=name, target_data=target_role,
                              reason="ancien rôle introuvable, création")
        return RoleAction(kind="rename", target_name=name, target_data=target_role,
                          current_role=existing, reason=f"renommer depuis `{existing.name}`")

    # origin == "existing"
    existing = _find_role(guild, target_role)
    if existing is None:
        warnings.append(f"Rôle existant `{name}` introuvable (id `{target_role.get('existing_id')}`).")
        return RoleAction(kind="create", target_name=name, target_data=target_role,
                          reason="rôle marqué existing mais introuvable, création")
    return RoleAction(kind="update_perms", target_name=name, target_data=target_role,
                      current_role=existing, reason="ajustement éventuel des perms et hoist/color")


def _diff_category(guild: discord.Guild, target_cat: dict, warnings: list[str]) -> CategoryAction:
    name = target_cat.get("name", "?")
    origin = target_cat.get("_origin", "new")
    existing = _find_category(guild, target_cat)

    if origin == "new":
        if existing:
            kind = "update_overrides"
            reason = "catégorie 'new' déjà présente — mise à jour overrides"
        else:
            kind = "create"
            reason = "catégorie V2 à créer"
    elif origin == "rename":
        if existing is None:
            warnings.append(f"Catégorie à renommer `{target_cat.get('old_name')}` → `{name}` introuvable.")
            kind = "create"
            reason = "ancienne catégorie introuvable, création"
        else:
            kind = "rename"
            reason = f"renommer depuis `{existing.name}`"
    else:  # existing
        if existing is None:
            warnings.append(f"Catégorie existante `{name}` introuvable.")
            kind = "create"
            reason = "marquée existing mais introuvable"
        else:
            kind = "update_overrides"
            reason = "ajustement overrides"

    cat_action = CategoryAction(kind=kind, target_name=name, target_data=target_cat,
                                current_category=existing, reason=reason)

    target_channel_names = {c["name"] for c in target_cat.get("channels", [])}

    for ch_target in target_cat.get("channels", []):
        ch_name = ch_target["name"]
        current_in_target_cat = None
        if existing:
            for ch in existing.channels:
                if ch.name == ch_name:
                    current_in_target_cat = ch
                    break

        if current_in_target_cat:
            cat_action.channel_actions.append(ChannelAction(
                kind="skip", target_name=ch_name, parent_category_name=name,
                target_data=ch_target, current_channel=current_in_target_cat,
                reason="déjà dans la bonne catégorie"
            ))
            continue

        elsewhere = _find_channel_in_guild(guild, ch_name)
        if elsewhere:
            cat_action.channel_actions.append(ChannelAction(
                kind="move", target_name=ch_name, parent_category_name=name,
                target_data=ch_target, current_channel=elsewhere,
                reason=f"déplacer depuis `{elsewhere.category.name if elsewhere.category else 'racine'}`"
            ))
        else:
            cat_action.channel_actions.append(ChannelAction(
                kind="create", target_name=ch_name, parent_category_name=name,
                target_data=ch_target,
                reason="salon V2 à créer"
            ))

    # Salons restants dans la catégorie existante qui ne sont pas dans la cible
    # → ils seront archivés au niveau global (collectés ailleurs).
    return cat_action


def compute_diff(guild: discord.Guild, target: Optional[dict] = None) -> Diff:
    """Calcule le diff complet entre le serveur et la cible V2."""
    if target is None:
        target = load_target()

    diff = Diff(target=target)

    # 1. Rôles
    target_role_ids: set[str] = set()
    target_role_names: set[str] = set()
    for tr in target.get("roles", []):
        action = _diff_role(guild, tr, diff.warnings)
        diff.role_actions.append(action)
        if tr.get("existing_id"):
            target_role_ids.add(str(tr["existing_id"]))
        target_role_names.add(tr.get("name", ""))
        if tr.get("old_name"):
            target_role_names.add(tr["old_name"])

    # 2. Catégories + salons cibles
    target_category_ids: set[str] = set()
    target_category_names: set[str] = set()
    target_channel_names: set[str] = set()
    for tc in target.get("categories", []):
        action = _diff_category(guild, tc, diff.warnings)
        diff.category_actions.append(action)
        if tc.get("existing_id"):
            target_category_ids.add(str(tc["existing_id"]))
        target_category_names.add(tc.get("name", ""))
        if tc.get("old_name"):
            target_category_names.add(tc["old_name"])
        for ch in tc.get("channels", []):
            target_channel_names.add(ch["name"])

    archive_name = target.get("_metadata", {}).get("archive_category_name", "🗄️ ▸ _archive")
    target_category_names.add(archive_name)

    # 3. Orphelins (catégories et salons non listés dans la cible)
    if target.get("_metadata", {}).get("archive_if_not_in_target", False):
        for cat in guild.categories:
            if str(cat.id) in target_category_ids:
                continue
            if cat.name in target_category_names:
                continue
            diff.orphan_categories.append(cat)

        for ch in guild.channels:
            if isinstance(ch, discord.CategoryChannel):
                continue
            if ch.name in target_channel_names:
                continue
            # Si déjà dans une catégorie cible, c'est un orphelin dans cette catégorie
            diff.orphan_channels.append(ch)

    return diff


def perm_dict_to_overwrite(allow_list: list[str], deny_list: list[str]) -> discord.PermissionOverwrite:
    """Convertit listes allow/deny du target en PermissionOverwrite discord.py."""
    ow = discord.PermissionOverwrite()
    for p in allow_list:
        attr = _normalize_perm(p)
        if hasattr(ow, attr):
            setattr(ow, attr, True)
    for p in deny_list:
        attr = _normalize_perm(p)
        if hasattr(ow, attr):
            setattr(ow, attr, False)
    return ow


def perm_list_to_permissions(perm_list: list[str]) -> discord.Permissions:
    """Convertit la liste compacte de perms en Permissions complète."""
    perms = discord.Permissions.none()
    for p in perm_list:
        attr = _normalize_perm(p)
        if hasattr(perms, attr):
            setattr(perms, attr, True)
    return perms


def validate_target(target: dict) -> list[str]:
    """Validation syntaxique du fichier cible. Retourne liste d'erreurs (vide si OK)."""
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
            attr = _normalize_perm(p)
            if attr not in VALID_PERMISSIONS:
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
                errors.append(f"categories[{i}] (`{name}`) : override référence rôle inconnu `{role_ref}`")
        for j, ch in enumerate(cat.get("channels", [])):
            if not ch.get("name"):
                errors.append(f"categories[{i}].channels[{j}] : nom manquant")
            ch_type = ch.get("type", "text")
            if ch_type not in ("text", "voice"):
                errors.append(f"categories[{i}].channels[{j}] (`{ch.get('name')}`) : type invalide `{ch_type}`")

    return errors
