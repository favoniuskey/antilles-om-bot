"""Gestion de la catégorie `_archive` : création + déplacement des orphelins."""

from __future__ import annotations

import discord


async def ensure_archive_category(
    guild: discord.Guild,
    name: str,
    administrator_role: discord.Role | None,
) -> discord.CategoryChannel:
    """Crée la catégorie d'archivage si absente, restrictive par défaut.

    Visible uniquement par Administrateur (et bien sûr le bot via ses
    permissions de rôle). Aucun rôle membre n'y a accès.
    """
    for c in guild.categories:
        if c.name == name:
            return c

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if administrator_role is not None:
        overwrites[administrator_role] = discord.PermissionOverwrite(
            view_channel=True, manage_channels=True
        )

    return await guild.create_category(
        name=name,
        overwrites=overwrites,
        reason="Migration V2 — catégorie d'archive pour éléments hors cible",
    )


async def archive_channel(
    channel: discord.abc.GuildChannel,
    archive_category: discord.CategoryChannel,
) -> None:
    """Déplace un salon vers l'archive et le sécurise (cache à tout sauf staff)."""
    if not hasattr(channel, "edit"):
        return
    try:
        await channel.edit(
            category=archive_category,
            sync_permissions=True,
            reason="Migration V2 — salon hors cible archivé",
        )
    except discord.Forbidden:
        pass


async def archive_orphan_category(
    category: discord.CategoryChannel,
    archive_category: discord.CategoryChannel,
) -> None:
    """Déplace tous les salons d'une catégorie orpheline vers l'archive,
    puis tente de supprimer la catégorie elle-même (qui devient vide).

    On ne supprime PAS si la catégorie contient encore des salons après le
    déplacement (sécurité — si un salon a refusé le move, on garde la cat).
    """
    moved = 0
    for ch in list(category.channels):
        try:
            await ch.edit(
                category=archive_category,
                sync_permissions=True,
                reason="Migration V2 — catégorie source archivée",
            )
            moved += 1
        except discord.Forbidden:
            pass

    # Recharger la catégorie ; si vide, on peut la supprimer
    await _safe_delete_if_empty(category)


async def _safe_delete_if_empty(category: discord.CategoryChannel) -> None:
    # Re-fetch via guild pour avoir l'état à jour
    fresh = category.guild.get_channel(category.id)
    if isinstance(fresh, discord.CategoryChannel) and not fresh.channels:
        try:
            await fresh.delete(reason="Migration V2 — catégorie vide après archivage des salons")
        except discord.Forbidden:
            pass
