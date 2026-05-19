"""Cog de maintenance de la structure V2 du serveur.

Fournit des slash commands pour vérifier la conformité du serveur à la
cible définie dans `migration/v2_target.json`, et pour réparer
ponctuellement un rôle ou un salon manquant.

Restreint à : Directeur communauté + Administrateur.
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from migration.applier import Applier
from migration.differ import (
    compute_diff,
    load_target,
    perm_dict_to_overwrite,
    perm_list_to_permissions,
)
from migration.reporter import Report


SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "migration" / "snapshots"


GOVERNANCE_ROLES = {"Directeur communauté", "Administrateur"}


def _is_governance(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    # Owner du serveur : toujours autorisé (avant que les rôles V2 existent)
    if interaction.guild.owner_id == member.id:
        return True
    # Permission Administrator effective (Super-Admin, Administrateur, etc.)
    if member.guild_permissions.administrator:
        return True
    # Rôles nommés explicitement V2
    return any(r.name in GOVERNANCE_ROLES for r in member.roles)


def require_governance():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _is_governance(interaction):
            return True
        await interaction.response.send_message(
            "🚫 Réservé à `Directeur communauté` ou `Administrateur`.",
            ephemeral=True,
        )
        return False
    return app_commands.check(predicate)


class StructureGuard(commands.Cog):
    """Vérification et réparation ponctuelle de la structure V2."""

    structure = app_commands.Group(name="structure", description="Maintenance structure V2")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /structure status
    # ------------------------------------------------------------------

    @structure.command(name="status", description="Vue compacte de la conformité V2")
    @require_governance()
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            target = load_target()
            diff = compute_diff(interaction.guild, target)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return

        n_roles_target = len(target.get("roles", []))
        n_roles_ok = sum(
            1 for ra in diff.role_actions if ra.kind in ("skip", "update_perms")
            and ra.current_role is not None
        )
        n_roles_missing = sum(1 for ra in diff.role_actions if ra.kind == "create")
        n_cats_target = len(target.get("categories", []))
        n_cats_ok = sum(
            1 for ca in diff.category_actions if ca.kind in ("update_overrides",)
            and ca.current_category is not None
        )
        n_cats_missing = sum(1 for ca in diff.category_actions if ca.kind == "create")

        embed = discord.Embed(
            title="État conformité V2",
            color=discord.Color.green() if (n_roles_missing + n_cats_missing == 0) else discord.Color.orange(),
        )
        embed.add_field(name="Rôles", value=f"{n_roles_ok}/{n_roles_target} OK · {n_roles_missing} à créer", inline=False)
        embed.add_field(name="Catégories", value=f"{n_cats_ok}/{n_cats_target} OK · {n_cats_missing} à créer", inline=False)
        embed.add_field(name="Salons orphelins (hors cible)", value=str(len(diff.orphan_channels)), inline=False)
        if diff.warnings:
            embed.add_field(name="⚠️ Alertes", value="\n".join(f"• {w}" for w in diff.warnings[:5]), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /structure verify
    # ------------------------------------------------------------------

    @structure.command(name="verify", description="Compare l'état réel à la cible V2")
    @require_governance()
    async def verify(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            target = load_target()
            diff = compute_diff(interaction.guild, target)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return

        lines: list[str] = ["**Rôles**"]
        for ra in diff.role_actions:
            if ra.kind == "skip":
                lines.append(f"✅ `{ra.target_name}`")
            elif ra.kind == "update_perms":
                lines.append(f"🔧 `{ra.target_name}` — perms à ajuster")
            elif ra.kind == "create":
                lines.append(f"❌ `{ra.target_name}` — manquant")
            elif ra.kind == "rename":
                lines.append(f"✏️ `{ra.target_name}` — renommage attendu")
            elif ra.kind == "flag":
                lines.append(f"🚩 `{ra.target_name}` — à arbitrer")

        lines.append("")
        lines.append("**Catégories**")
        for ca in diff.category_actions:
            if ca.kind == "create":
                lines.append(f"❌ `{ca.target_name}` — manquante")
            elif ca.kind == "rename":
                lines.append(f"✏️ `{ca.target_name}` — renommage attendu")
            else:
                lines.append(f"✅ `{ca.target_name}`")
            for cha in ca.channel_actions:
                icon = {"skip": "  ✅", "create": "  ❌", "move": "  📦", "rename": "  ✏️"}.get(cha.kind, "  •")
                lines.append(f"{icon} #{cha.target_name}")

        text = "\n".join(lines)
        if len(text) <= 1900:
            await interaction.followup.send(text, ephemeral=True)
        else:
            buf = io.BytesIO(text.encode("utf-8"))
            await interaction.followup.send(
                "Rapport trop long, fichier joint.",
                file=discord.File(buf, filename="structure_verify.md"),
                ephemeral=True,
            )

    # ------------------------------------------------------------------
    # /structure diff
    # ------------------------------------------------------------------

    @structure.command(name="diff", description="Rapport détaillé des écarts (markdown)")
    @require_governance()
    async def diff(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            target = load_target()
            d = compute_diff(interaction.guild, target)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return

        out = ["# Diff structure V2", ""]
        out.append("## Rôles")
        for ra in d.role_actions:
            out.append(f"- **{ra.kind}** `{ra.target_name}` — {ra.reason}")
        out.append("")
        out.append("## Catégories")
        for ca in d.category_actions:
            out.append(f"- **{ca.kind}** `{ca.target_name}` — {ca.reason}")
            for cha in ca.channel_actions:
                out.append(f"  - {cha.kind} #{cha.target_name} — {cha.reason}")
        if d.orphan_channels:
            out.append("")
            out.append("## Salons orphelins (hors cible)")
            for ch in d.orphan_channels:
                out.append(f"- #{ch.name}")
        if d.warnings:
            out.append("")
            out.append("## ⚠️ Warnings")
            for w in d.warnings:
                out.append(f"- {w}")

        buf = io.BytesIO("\n".join(out).encode("utf-8"))
        await interaction.followup.send(
            file=discord.File(buf, filename="structure_diff.md"),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /structure fix role
    # ------------------------------------------------------------------

    fix = app_commands.Group(name="fix", description="Réparer un élément V2 manquant",
                             parent=structure)

    @fix.command(name="role", description="Re-crée un rôle V2 manquant")
    @app_commands.describe(name="Nom exact du rôle (tel que défini dans v2_target.json)")
    @require_governance()
    async def fix_role(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        target = load_target()
        spec = next((r for r in target.get("roles", []) if r.get("name") == name), None)
        if spec is None:
            await interaction.followup.send(f"❌ Rôle `{name}` introuvable dans v2_target.json", ephemeral=True)
            return
        existing = discord.utils.get(interaction.guild.roles, name=name)
        if existing:
            await interaction.followup.send(f"ℹ️ Rôle `{name}` déjà présent (id {existing.id})", ephemeral=True)
            return
        try:
            role = await interaction.guild.create_role(
                name=name,
                permissions=perm_list_to_permissions(spec.get("permissions", [])),
                color=discord.Color(spec.get("color", 0)),
                hoist=spec.get("hoist", False),
                mentionable=spec.get("mentionable", False),
                reason=f"/structure fix role par {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission refusée", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Rôle `{role.name}` créé (id {role.id})", ephemeral=True)

    @fix.command(name="channel", description="Re-crée un salon V2 manquant")
    @app_commands.describe(name="Nom exact du salon (tel que défini dans v2_target.json)")
    @require_governance()
    async def fix_channel(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        target = load_target()
        parent_cat_spec = None
        ch_spec = None
        for cat in target.get("categories", []):
            for ch in cat.get("channels", []):
                if ch.get("name") == name:
                    parent_cat_spec = cat
                    ch_spec = ch
                    break
            if ch_spec:
                break

        if ch_spec is None:
            await interaction.followup.send(f"❌ Salon `{name}` introuvable dans v2_target.json", ephemeral=True)
            return

        parent = discord.utils.get(interaction.guild.categories, name=parent_cat_spec["name"])
        if parent is None:
            await interaction.followup.send(
                f"❌ Catégorie parente `{parent_cat_spec['name']}` absente du serveur",
                ephemeral=True,
            )
            return

        if discord.utils.get(parent.channels, name=name):
            await interaction.followup.send(f"ℹ️ Salon `{name}` déjà présent dans `{parent.name}`", ephemeral=True)
            return

        try:
            if ch_spec.get("type") == "voice":
                ch = await interaction.guild.create_voice_channel(name=name, category=parent)
            else:
                ch = await interaction.guild.create_text_channel(name=name, category=parent)
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission refusée", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Salon `#{ch.name}` créé dans `{parent.name}`", ephemeral=True)

    # ------------------------------------------------------------------
    # /structure fix-category-names
    # ------------------------------------------------------------------

    @structure.command(
        name="fix-category-names",
        description="Renomme les catégories existantes selon les noms V2",
    )
    @require_governance()
    async def fix_category_names(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        target = load_target()
        renamed: list[tuple[str, str]] = []
        skipped: list[str] = []
        for cat_spec in target.get("categories", []):
            target_name = cat_spec.get("name")
            cat = None
            if cat_spec.get("existing_id"):
                cat = guild.get_channel(int(cat_spec["existing_id"]))
                if not isinstance(cat, discord.CategoryChannel):
                    cat = None
            if cat is None and cat_spec.get("old_name"):
                cat = discord.utils.get(guild.categories, name=cat_spec["old_name"])
            if cat is None:
                cat = discord.utils.get(guild.categories, name=target_name)
            if cat is None:
                continue
            if cat.name == target_name:
                continue
            old = cat.name
            try:
                await cat.edit(name=target_name, reason="Fix V2 — nom de catégorie")
                renamed.append((old, target_name))
            except discord.Forbidden:
                skipped.append(old)

        lines = []
        if renamed:
            lines.append(f"✅ **{len(renamed)} catégories renommées** :")
            for old, new in renamed:
                lines.append(f"• `{old}` → `{new}`")
        else:
            lines.append("ℹ️ Toutes les catégories sont déjà au bon nom.")
        if skipped:
            lines.append(f"\n⚠️ Permission refusée pour : {', '.join(skipped)}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------
    # /structure restore-channels
    # ------------------------------------------------------------------

    # Mapping fixe : salons archivés par erreur (vocaux et forums)
    # à remettre dans leur catégorie V2 logique.
    _RESTORE_MAPPING: dict[str, str] = {
        "1454596719508717568": "💬 ▸ COMMUNAUTÉ",   # 🌴 Créer ton salon (voice)
        "1228496187208761444": "💬 ▸ COMMUNAUTÉ",   # 🔊・Général (voice)
        "1228497793211957358": "💬 ▸ COMMUNAUTÉ",   # 🔊・Coin contrôleurs (voice)
        "1228497842482446376": "💬 ▸ COMMUNAUTÉ",   # 🔊・Coin pilotes (voice)
        "1307863639327244318": "💬 ▸ COMMUNAUTÉ",   # 📋 💡・suggestions (forum)
        "1228751101164126360": "🎫 ▸ SUPPORT",      # 📋 ❓・aide (forum)
        "1228753256050593926": "📚 ▸ DOCUMENTATION", # 📋 ✅・notams-updates (forum)
        "1414656319105007637": "✈️ ▸ FLY TROPIK",   # 🔊 Discussion FLYTROPIK (voice)
    }

    @structure.command(
        name="restore-channels",
        description="Sort de _archive les vocaux/forums utiles vers leur catégorie V2",
    )
    @require_governance()
    async def restore_channels(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        moved: list[tuple[str, str]] = []
        not_found: list[str] = []
        forbidden: list[str] = []
        for ch_id, target_cat_name in self._RESTORE_MAPPING.items():
            ch = guild.get_channel(int(ch_id))
            if ch is None:
                not_found.append(ch_id)
                continue
            target_cat = discord.utils.get(guild.categories, name=target_cat_name)
            if target_cat is None:
                not_found.append(f"cat:{target_cat_name}")
                continue
            if ch.category and ch.category.id == target_cat.id:
                continue
            try:
                await ch.edit(
                    category=target_cat,
                    sync_permissions=True,
                    reason="Restauration salon archivé par erreur",
                )
                moved.append((ch.name, target_cat_name))
            except discord.Forbidden:
                forbidden.append(ch.name)

        lines = []
        if moved:
            lines.append(f"✅ **{len(moved)} salons restaurés** :")
            for ch_name, cat_name in moved:
                lines.append(f"• `{ch_name}` → {cat_name}")
        else:
            lines.append("ℹ️ Aucun salon à restaurer (déjà tous au bon endroit).")
        if not_found:
            lines.append(f"\n⚠️ Introuvables : {', '.join(not_found)}")
        if forbidden:
            lines.append(f"\n⚠️ Permission refusée : {', '.join(forbidden)}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------
    # /structure fix-positions
    # ------------------------------------------------------------------

    @structure.command(
        name="fix-positions",
        description="Réorganise les positions des rôles selon la cible V2",
    )
    @require_governance()
    async def fix_positions(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        try:
            target = load_target()
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return

        # Collecter les rôles à réorganiser
        reorderable: list[tuple[discord.Role, int]] = []
        for role_spec in target.get("roles", []):
            if role_spec.get("_protected"):
                continue
            pos_rel = role_spec.get("position_rel")
            if pos_rel is None:
                continue
            # Match par ID si dispo, sinon par nom
            role = None
            if role_spec.get("existing_id"):
                role = guild.get_role(int(role_spec["existing_id"]))
            if role is None:
                role = discord.utils.get(guild.roles, name=role_spec["name"])
            if role is None or role.is_default() or role.managed:
                continue
            reorderable.append((role, pos_rel))

        if not reorderable:
            await interaction.followup.send("ℹ️ Aucun rôle à réorganiser.", ephemeral=True)
            return

        reorderable.sort(key=lambda x: -x[1])

        bot_top = guild.me.top_role.position
        max_abs = bot_top - 1

        positions: dict[discord.Role, int] = {}
        abs_pos = max_abs
        skipped: list[str] = []
        for role, _ in reorderable:
            if abs_pos < 1:
                skipped.append(role.name)
                continue
            positions[role] = abs_pos
            abs_pos -= 1

        try:
            await guild.edit_role_positions(positions=positions)
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission refusée pour réorganiser les rôles.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Erreur HTTP : {e}", ephemeral=True)
            return

        lines = [f"✅ **{len(positions)} rôles réorganisés** (du plus haut au plus bas) :", ""]
        for role, p in sorted(positions.items(), key=lambda x: -x[1])[:25]:
            lines.append(f"`{p:>2}` · {role.mention}")
        if len(positions) > 25:
            lines.append(f"… et {len(positions) - 25} de plus")
        if skipped:
            lines.append("")
            lines.append(f"⚠️ Non placés (plus de positions disponibles) : {', '.join(skipped)}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------
    # /structure migrate-dry-run
    # ------------------------------------------------------------------

    @structure.command(
        name="migrate-dry-run",
        description="Génère le rapport de migration V2 sans rien modifier",
    )
    @require_governance()
    async def migrate_dry_run(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        try:
            target = load_target()
            diff = compute_diff(guild, target)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return

        report = Report("dry-run")
        report.h2("Cible")
        report.bullet(f"Serveur : `{guild.name}` (`{guild.id}`)")
        report.bullet(f"Membres : {guild.member_count}")
        report.bullet(f"Déclenché par : {interaction.user} (`{interaction.user.id}`)")

        applier = Applier(guild, diff, report, dry_run=True)
        await applier.run_all()
        path = report.save()

        n_alerts = len(report.alerts)
        summary = (
            f"**Dry-run terminé**\n"
            f"• Alertes : {n_alerts}\n"
            f"• Stats : "
            + ", ".join(f"{k}={v}" for k, v in report.stats.items())
        )

        buf = io.BytesIO(str(report).encode("utf-8"))
        await interaction.followup.send(
            content=summary,
            file=discord.File(buf, filename=path.name),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /structure migrate-apply
    # ------------------------------------------------------------------

    @structure.command(
        name="migrate-apply",
        description="Applique la refonte V2 (confirmation requise)",
    )
    @require_governance()
    async def migrate_apply(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild

        # Pré-check rapide : on calcule le diff pour donner un résumé
        try:
            target = load_target()
            diff = compute_diff(guild, target)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return

        n_create = sum(1 for ra in diff.role_actions if ra.kind == "create")
        n_rename = sum(1 for ra in diff.role_actions if ra.kind == "rename")
        n_cat_create = sum(1 for ca in diff.category_actions if ca.kind == "create")
        n_ch_create = sum(
            1 for ca in diff.category_actions for cha in ca.channel_actions
            if cha.kind == "create"
        )
        n_orphans = len(diff.orphan_channels)

        embed = discord.Embed(
            title="⚠️ Confirmation migration V2",
            description=(
                "Tu es sur le point d'**appliquer** la refonte V2.\n\n"
                "**Un snapshot complet sera enregistré avant exécution.**\n"
                "Le rollback est possible via `/structure rollback`."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(name="Rôles à créer", value=str(n_create))
        embed.add_field(name="Rôles à renommer", value=str(n_rename))
        embed.add_field(name="Catégories à créer", value=str(n_cat_create))
        embed.add_field(name="Salons à créer", value=str(n_ch_create))
        embed.add_field(name="Salons à archiver", value=str(n_orphans))
        embed.add_field(name="Alertes", value=str(len(diff.warnings)))

        view = ConfirmMigrationView(self.bot, interaction.user.id, target, diff)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ------------------------------------------------------------------
    # /structure snapshots & rollback
    # ------------------------------------------------------------------

    @structure.command(name="snapshots", description="Liste les snapshots disponibles")
    @require_governance()
    async def list_snapshots(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not SNAPSHOTS_DIR.exists():
            await interaction.followup.send("Aucun snapshot enregistré.", ephemeral=True)
            return
        snaps = sorted(SNAPSHOTS_DIR.glob("*.json"), reverse=True)
        if not snaps:
            await interaction.followup.send("Aucun snapshot enregistré.", ephemeral=True)
            return
        lines = [f"**Snapshots disponibles** ({len(snaps)})", ""]
        for s in snaps[:15]:
            size_kb = s.stat().st_size / 1024
            lines.append(f"• `{s.stem}` — {size_kb:.1f} KB")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @structure.command(name="rollback", description="Restaure l'état depuis un snapshot")
    @app_commands.describe(snapshot_id="ID du snapshot (voir /structure snapshots)")
    @require_governance()
    async def rollback(self, interaction: discord.Interaction, snapshot_id: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        snap_path = SNAPSHOTS_DIR / f"{snapshot_id}.json"
        if not snap_path.exists():
            await interaction.followup.send(
                f"❌ Snapshot `{snapshot_id}` introuvable. Vois `/structure snapshots`.",
                ephemeral=True,
            )
            return

        view = ConfirmRollbackView(self.bot, interaction.user.id, snap_path)
        with snap_path.open("r", encoding="utf-8") as f:
            snap = json.load(f)
        embed = discord.Embed(
            title="⚠️ Confirmation rollback",
            description=(
                f"Restauration depuis `{snap_path.name}`\n"
                f"Pris le : `{snap.get('_snapshot_at')}`\n\n"
                f"Cela peut **supprimer des rôles/salons créés après le snapshot** et "
                f"restaurer les noms/perms précédents."
            ),
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @rollback.autocomplete("snapshot_id")
    async def rollback_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if not SNAPSHOTS_DIR.exists():
            return []
        snaps = sorted(SNAPSHOTS_DIR.glob("*.json"), reverse=True)
        return [
            app_commands.Choice(name=s.stem, value=s.stem)
            for s in snaps
            if current.lower() in s.stem.lower()
        ][:25]


# ----------------------------------------------------------------------
# Vues (boutons) de confirmation
# ----------------------------------------------------------------------

class ConfirmMigrationView(discord.ui.View):
    """Confirme l'apply de la migration via boutons."""

    def __init__(self, bot: commands.Bot, requester_id: int, target: dict, diff) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.requester_id = requester_id
        self.target = target
        self.diff = diff
        self.handled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Cette confirmation appartient à quelqu'un d'autre.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirmer et appliquer", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.handled:
            return
        self.handled = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🚀 Migration en cours… (peut prendre 1-3 min)", view=self)

        guild = interaction.guild

        # Snapshot
        from migration.migrate_v2 import snapshot_guild, save_snapshot
        snap = snapshot_guild(guild)
        snap_path = save_snapshot(snap)

        # Report + apply
        report = Report("apply")
        report.h2("Snapshot pré-apply")
        report.bullet(f"Fichier : `{snap_path.name}`")
        report.bullet(f"Rollback : `/structure rollback snapshot_id:{snap_path.stem}`")
        report.bullet(f"Déclenché par : {interaction.user}")

        applier = Applier(guild, self.diff, report, dry_run=False)
        try:
            success = await applier.run_all()
        except Exception as e:
            report.alert(f"Exception : {e}")
            success = False
        path = report.save()

        summary = "✅ Migration appliquée." if success else "⚠️ Migration interrompue, voir rapport."
        summary += f"\nSnapshot : `{snap_path.stem}`"
        buf = io.BytesIO(str(report).encode("utf-8"))
        await interaction.followup.send(
            content=summary,
            file=discord.File(buf, filename=path.name),
            ephemeral=True,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.handled = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Migration annulée.", view=self)


class ConfirmRollbackView(discord.ui.View):
    def __init__(self, bot: commands.Bot, requester_id: int, snap_path: Path) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.requester_id = requester_id
        self.snap_path = snap_path
        self.handled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Cette confirmation appartient à quelqu'un d'autre.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirmer rollback", style=discord.ButtonStyle.danger, emoji="♻️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.handled:
            return
        self.handled = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="♻️ Rollback en cours…", view=self)

        guild = interaction.guild
        with self.snap_path.open("r", encoding="utf-8") as f:
            snap = json.load(f)

        report = Report("rollback")
        report.h2("Rollback")
        report.bullet(f"Snapshot : `{self.snap_path.name}`")
        report.bullet(f"Pris le : `{snap.get('_snapshot_at')}`")

        snap_role_ids = {r["id"] for r in snap.get("roles", [])}
        snap_cat_ids = {c["id"] for c in snap.get("categories", [])}
        snap_ch_ids = {c["id"] for c in snap.get("channels", [])}

        for r in snap.get("roles", []):
            if r.get("is_default") or r.get("managed"):
                continue
            role = guild.get_role(int(r["id"]))
            if role is None:
                continue
            try:
                await role.edit(
                    name=r["name"],
                    permissions=discord.Permissions(r["permissions"]),
                    color=discord.Color(r["color"]),
                    hoist=r["hoist"],
                    mentionable=r["mentionable"],
                    reason="Rollback V2",
                )
                report.bullet(f"♻️ Rôle `{r['name']}` restauré")
            except discord.Forbidden:
                report.alert(f"Refus restauration `{r['name']}`")

        for role in list(guild.roles):
            if str(role.id) in snap_role_ids or role.is_default() or role.managed:
                continue
            try:
                await role.delete(reason="Rollback V2")
                report.bullet(f"🗑️ Rôle `{role.name}` supprimé")
            except discord.Forbidden:
                pass

        for ch_snap in snap.get("channels", []):
            ch = guild.get_channel(int(ch_snap["id"]))
            if ch is None:
                continue
            target_cat = None
            if ch_snap.get("category_id"):
                target_cat = guild.get_channel(int(ch_snap["category_id"]))
            if ch.category != target_cat:
                try:
                    await ch.edit(category=target_cat, reason="Rollback V2")
                    report.bullet(f"♻️ `{ch.name}` recatégorisé")
                except discord.Forbidden:
                    pass

        for ch in list(guild.channels):
            if isinstance(ch, discord.CategoryChannel):
                continue
            if str(ch.id) in snap_ch_ids:
                continue
            try:
                await ch.delete(reason="Rollback V2")
                report.bullet(f"🗑️ Salon `{ch.name}` supprimé")
            except discord.Forbidden:
                pass

        for cat in list(guild.categories):
            if str(cat.id) in snap_cat_ids:
                continue
            if cat.channels:
                report.alert(f"Catégorie `{cat.name}` non vide — non supprimée")
                continue
            try:
                await cat.delete(reason="Rollback V2")
                report.bullet(f"🗑️ Catégorie `{cat.name}` supprimée")
            except discord.Forbidden:
                pass

        path = report.save()
        buf = io.BytesIO(str(report).encode("utf-8"))
        await interaction.followup.send(
            content="♻️ Rollback terminé.",
            file=discord.File(buf, filename=path.name),
            ephemeral=True,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.handled = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Rollback annulé.", view=self)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StructureGuard(bot))
