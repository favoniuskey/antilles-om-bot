"""Application des 7 étapes du plan de migration V2.

Consomme un `Diff` produit par `differ.py` et un `Report` produit par
`reporter.py`. Effectue les modifications réelles sur le serveur Discord.

En mode dry-run : `Applier(..., dry_run=True)` n'effectue aucune écriture,
mais produit le même rapport que ce qui serait fait.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import discord

from . import archiver
from .differ import (
    CategoryAction,
    ChannelAction,
    Diff,
    RoleAction,
    perm_dict_to_overwrite,
    perm_list_to_permissions,
)
from .reporter import Report


class Applier:
    def __init__(
        self,
        guild: discord.Guild,
        diff: Diff,
        report: Report,
        dry_run: bool = False,
    ) -> None:
        self.guild = guild
        self.diff = diff
        self.report = report
        self.dry_run = dry_run
        # Mapping name → Role construit/maintenu pendant les étapes
        self._role_by_name: dict[str, discord.Role] = {r.name: r for r in guild.roles}
        # Mapping name → CategoryChannel
        self._category_by_name: dict[str, discord.CategoryChannel] = {
            c.name: c for c in guild.categories
        }
        self._archive_category: Optional[discord.CategoryChannel] = None

    # ------------------------------------------------------------------
    # Étape 1 — Gel et pre-checks
    # ------------------------------------------------------------------

    async def step1_pre_checks(self) -> bool:
        self.report.h2("Étape 1 — Pre-checks")
        bot_member = self.guild.me
        if bot_member is None:
            self.report.alert("Bot non présent dans la guild.")
            return False

        if not bot_member.guild_permissions.administrator:
            self.report.alert("Le bot n'a pas la permission Administrator. Migration impossible.")
            return False
        self.report.ok("Le bot a Administrator.")

        top_bot_role = bot_member.top_role
        self.report.bullet(f"Rôle le plus haut du bot : `{top_bot_role.name}` (position {top_bot_role.position})")

        roles_to_edit = [
            ra.current_role for ra in self.diff.role_actions
            if ra.kind in ("rename", "update_perms") and ra.current_role is not None
            and not ra.target_data.get("_protected", False)
        ]
        blocked = [r for r in roles_to_edit if r.position >= top_bot_role.position]
        if blocked:
            self.report.alert(
                f"Le bot ne peut pas modifier ces rôles (position ≥ top role bot) : "
                + ", ".join(f"`{r.name}`" for r in blocked)
            )
            return False
        self.report.ok("Hiérarchie OK — le bot peut modifier tous les rôles ciblés.")

        for w in self.diff.warnings:
            self.report.alert(w)

        return True

    # ------------------------------------------------------------------
    # Étape 2 — Rôles
    # ------------------------------------------------------------------

    async def step2_roles(self) -> None:
        self.report.h2("Étape 2 — Rôles")

        for action in self.diff.role_actions:
            await self._apply_role_action(action)

        # Désactiver Administrator sur les rôles non protégés qui l'ont encore
        # (en particulier `BOTS` selon V2 §5.3).
        await self._strip_admin_from_unprotected_bots()

    async def _apply_role_action(self, action: RoleAction) -> None:
        name = action.target_name

        if action.kind == "skip":
            self.report.bullet(f"⏭️ `{name}` — {action.reason}")
            if action.current_role:
                self._role_by_name[name] = action.current_role
            return

        if action.kind == "flag":
            self.report.bullet(f"🚩 `{name}` — {action.reason}")
            if action.current_role:
                self._role_by_name[name] = action.current_role
            return

        if action.kind == "create":
            self.report.bullet(f"➕ Créer rôle `{name}` — {action.reason}")
            self.report.stat("Rôles à créer", 1)
            if not self.dry_run:
                role = await self.guild.create_role(
                    name=name,
                    permissions=perm_list_to_permissions(action.target_data.get("permissions", [])),
                    color=discord.Color(action.target_data.get("color", 0)),
                    hoist=action.target_data.get("hoist", False),
                    mentionable=action.target_data.get("mentionable", False),
                    reason="Migration V2 — création rôle",
                )
                self._role_by_name[name] = role
            return

        if action.kind == "rename":
            old_name = action.current_role.name if action.current_role else "?"
            self.report.bullet(f"✏️ Renommer rôle `{old_name}` → `{name}`")
            self.report.stat("Rôles à renommer", 1)
            if not self.dry_run and action.current_role:
                await action.current_role.edit(
                    name=name,
                    permissions=perm_list_to_permissions(action.target_data.get("permissions", [])),
                    color=discord.Color(action.target_data.get("color", 0)),
                    hoist=action.target_data.get("hoist", False),
                    mentionable=action.target_data.get("mentionable", False),
                    reason="Migration V2 — renommage rôle",
                )
                self._role_by_name[name] = action.current_role
                # Nettoyer l'ancienne entrée
                self._role_by_name.pop(old_name, None)
            return

        if action.kind == "update_perms":
            self.report.bullet(f"🔧 Mettre à jour rôle `{name}` — perms/color/hoist")
            self.report.stat("Rôles à mettre à jour", 1)
            if not self.dry_run and action.current_role:
                # On ne modifie pas les perms si la liste est vide ET que le rôle existe déjà
                # avec d'autres perms — sécurité pour ne pas vider accidentellement.
                # Mais si "permissions" est explicitement dans target_data, on applique.
                kwargs: dict = {}
                if "permissions" in action.target_data:
                    kwargs["permissions"] = perm_list_to_permissions(
                        action.target_data["permissions"]
                    )
                if "color" in action.target_data:
                    kwargs["color"] = discord.Color(action.target_data["color"])
                if "hoist" in action.target_data:
                    kwargs["hoist"] = action.target_data["hoist"]
                if "mentionable" in action.target_data:
                    kwargs["mentionable"] = action.target_data["mentionable"]
                if kwargs:
                    await action.current_role.edit(
                        **kwargs, reason="Migration V2 — mise à jour rôle"
                    )
                self._role_by_name[name] = action.current_role
            elif action.current_role:
                self._role_by_name[name] = action.current_role

    async def _strip_admin_from_unprotected_bots(self) -> None:
        for action in self.diff.role_actions:
            data = action.target_data
            if data.get("_protected"):
                continue
            if data.get("name") in ("BOTS",):
                role = self._role_by_name.get(data["name"])
                if role and role.permissions.administrator:
                    self.report.bullet(f"🛡️ Retirer Administrator de `{role.name}` (V2 §5.3)")
                    self.report.stat("Administrator retiré", 1)
                    if not self.dry_run:
                        perms = role.permissions
                        perms.update(administrator=False)
                        await role.edit(
                            permissions=perms,
                            reason="Migration V2 — Administrator retiré aux bots externes",
                        )

    # ------------------------------------------------------------------
    # Étape 3 — Catégories
    # ------------------------------------------------------------------

    async def step3_categories(self) -> None:
        self.report.h2("Étape 3 — Catégories")
        for action in self.diff.category_actions:
            await self._apply_category_action(action)

        # Catégorie d'archive
        archive_name = self.diff.target.get("_metadata", {}).get(
            "archive_category_name", "🗄️ ▸ _archive"
        )
        need_archive = bool(self.diff.orphan_channels or self.diff.orphan_categories)
        if need_archive:
            self.report.bullet(f"➕ Créer/réutiliser catégorie d'archive `{archive_name}`")
            self.report.stat("Catégorie d'archive", 1)
            if not self.dry_run:
                admin_role = self._role_by_name.get("Administrateur")
                self._archive_category = await archiver.ensure_archive_category(
                    self.guild, archive_name, admin_role
                )
                self._category_by_name[archive_name] = self._archive_category

    async def _apply_category_action(self, action: CategoryAction) -> None:
        name = action.target_name

        if action.kind == "create":
            self.report.bullet(f"➕ Créer catégorie `{name}`")
            self.report.stat("Catégories à créer", 1)
            if not self.dry_run:
                cat = await self.guild.create_category(
                    name=name, reason="Migration V2 — création catégorie"
                )
                self._category_by_name[name] = cat
                action.current_category = cat
            return

        if action.kind == "rename":
            old = action.current_category.name if action.current_category else "?"
            self.report.bullet(f"✏️ Renommer catégorie `{old}` → `{name}`")
            self.report.stat("Catégories à renommer", 1)
            if not self.dry_run and action.current_category:
                await action.current_category.edit(
                    name=name, reason="Migration V2 — renommage catégorie"
                )
                self._category_by_name[name] = action.current_category
                self._category_by_name.pop(old, None)
            return

        if action.kind == "update_overrides":
            self.report.bullet(f"🔧 Mettre à jour overrides catégorie `{name}`")
            self.report.stat("Catégories — overrides MAJ", 1)
            if action.current_category:
                self._category_by_name[name] = action.current_category
            return

    # ------------------------------------------------------------------
    # Étape 4 — Permissions par catégorie
    # ------------------------------------------------------------------

    async def step4_category_permissions(self) -> None:
        self.report.h2("Étape 4 — Permissions par catégorie")
        for cat_target in self.diff.target.get("categories", []):
            name = cat_target.get("name")
            cat = self._category_by_name.get(name)
            if cat is None:
                self.report.alert(f"Catégorie `{name}` absente après étape 3 — skip overrides")
                continue
            overrides_spec = cat_target.get("overrides", {})
            if not overrides_spec:
                continue

            built: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}
            for role_ref, spec in overrides_spec.items():
                target_obj = self._resolve_role_ref(role_ref)
                if target_obj is None:
                    self.report.alert(
                        f"Catégorie `{name}` : override référence rôle inconnu `{role_ref}` — ignoré"
                    )
                    continue
                built[target_obj] = perm_dict_to_overwrite(
                    spec.get("allow", []), spec.get("deny", [])
                )

            self.report.bullet(f"🔐 `{name}` : {len(built)} overrides")
            self.report.stat("Overrides appliqués", len(built))
            if not self.dry_run:
                try:
                    await cat.edit(
                        overwrites=built,
                        reason="Migration V2 — application overrides catégorie",
                    )
                except discord.Forbidden:
                    self.report.alert(f"Permission refusée pour éditer overrides de `{name}`")

    def _resolve_role_ref(self, ref: str) -> Optional[discord.abc.Snowflake]:
        if ref == "@everyone":
            return self.guild.default_role
        return self._role_by_name.get(ref)

    # ------------------------------------------------------------------
    # Étape 5 — Salons
    # ------------------------------------------------------------------

    async def step5_channels(self) -> None:
        self.report.h2("Étape 5 — Salons")

        # 5a. Création / déplacement / renommage selon ChannelAction
        for cat_action in self.diff.category_actions:
            parent = self._category_by_name.get(cat_action.target_name)
            for ch_action in cat_action.channel_actions:
                await self._apply_channel_action(ch_action, parent)

        # 5b. Overrides spécifiques de salons (rares — la plupart héritent)
        for cat_target in self.diff.target.get("categories", []):
            parent = self._category_by_name.get(cat_target.get("name"))
            if parent is None:
                continue
            for ch_target in cat_target.get("channels", []):
                ch_overrides = ch_target.get("overrides")
                if not ch_overrides:
                    continue
                channel = discord.utils.get(parent.channels, name=ch_target["name"])
                if channel is None:
                    continue
                await self._apply_channel_overrides(channel, ch_overrides)

        # 5c. Archivage des orphelins
        if self.diff.orphan_channels or self.diff.orphan_categories:
            await self._archive_orphans()

    async def _apply_channel_action(
        self,
        action: ChannelAction,
        parent: Optional[discord.CategoryChannel],
    ) -> None:
        name = action.target_name
        ch_type = action.target_data.get("type", "text")

        if action.kind == "skip":
            return

        if action.kind == "create":
            self.report.bullet(f"➕ Créer salon `{name}` dans `{action.parent_category_name}`")
            self.report.stat("Salons à créer", 1)
            if not self.dry_run and parent is not None:
                if ch_type == "voice":
                    await self.guild.create_voice_channel(
                        name=name, category=parent,
                        reason="Migration V2 — création salon"
                    )
                else:
                    await self.guild.create_text_channel(
                        name=name, category=parent,
                        topic=action.target_data.get("topic"),
                        reason="Migration V2 — création salon"
                    )
            return

        if action.kind == "move":
            self.report.bullet(
                f"📦 Déplacer salon `{name}` vers `{action.parent_category_name}`"
            )
            self.report.stat("Salons à déplacer", 1)
            if not self.dry_run and action.current_channel and parent is not None:
                try:
                    await action.current_channel.edit(
                        category=parent,
                        sync_permissions=True,
                        reason="Migration V2 — reclassement salon",
                    )
                except discord.Forbidden:
                    self.report.alert(f"Permission refusée pour déplacer `{name}`")
            return

        if action.kind == "rename":
            old = action.current_channel.name if action.current_channel else "?"
            self.report.bullet(f"✏️ Renommer salon `{old}` → `{name}`")
            self.report.stat("Salons à renommer", 1)
            if not self.dry_run and action.current_channel:
                await action.current_channel.edit(
                    name=name, reason="Migration V2 — renommage salon"
                )

    async def _apply_channel_overrides(
        self,
        channel: discord.abc.GuildChannel,
        overrides_spec: dict,
    ) -> None:
        for role_ref, spec in overrides_spec.items():
            target_obj = self._resolve_role_ref(role_ref)
            if target_obj is None:
                continue
            ow = perm_dict_to_overwrite(spec.get("allow", []), spec.get("deny", []))
            self.report.bullet(f"  ↳ override `{channel.name}` pour `{role_ref}`")
            if not self.dry_run:
                try:
                    await channel.set_permissions(
                        target_obj, overwrite=ow,
                        reason="Migration V2 — override salon",
                    )
                except discord.Forbidden:
                    self.report.alert(f"Refus override `{channel.name}` pour `{role_ref}`")

    async def _archive_orphans(self) -> None:
        self.report.h3("Archivage des orphelins")

        if self._archive_category is None and not self.dry_run:
            admin_role = self._role_by_name.get("Administrateur")
            archive_name = self.diff.target.get("_metadata", {}).get(
                "archive_category_name", "🗄️ ▸ _archive"
            )
            self._archive_category = await archiver.ensure_archive_category(
                self.guild, archive_name, admin_role
            )

        for ch in self.diff.orphan_channels:
            # Ignorer les salons déjà dans une catégorie cible OU déjà dans l'archive
            if ch.category and ch.category.name in self._category_by_name:
                if ch.category != self._archive_category:
                    continue
            self.report.bullet(f"🗄️ Archiver salon `{ch.name}`")
            self.report.stat("Salons archivés", 1)
            if not self.dry_run and self._archive_category:
                await archiver.archive_channel(ch, self._archive_category)

        for cat in self.diff.orphan_categories:
            self.report.bullet(f"🗄️ Archiver catégorie orpheline `{cat.name}` (contenu déplacé)")
            self.report.stat("Catégories archivées", 1)
            if not self.dry_run and self._archive_category:
                await archiver.archive_orphan_category(cat, self._archive_category)

    # ------------------------------------------------------------------
    # Étape 6 — Tests automatisés (V2 §7.1)
    # ------------------------------------------------------------------

    async def step6_tests(self) -> None:
        self.report.h2("Étape 6 — Tests automatisés")

        non_verif = self._role_by_name.get("Non vérifié")
        membre = self._role_by_name.get("Membre")
        accueil = self._category_by_name.get("👋 ▸ ACCUEIL")
        communaute = self._category_by_name.get("💬 ▸ COMMUNAUTÉ")
        outils = self._category_by_name.get("🛠️ ▸ OUTILS ATC / BOT")
        bot_principal = self._role_by_name.get("Antilles - Outre Mer")

        def _check(label: str, cond: bool, detail: str = "") -> None:
            if cond:
                self.report.ok(f"{label} ✓ {detail}")
            else:
                self.report.alert(f"{label} ✗ {detail}")

        if non_verif and accueil:
            ow = accueil.permissions_for_role(non_verif) if hasattr(accueil, "permissions_for_role") else None
            # discord.py n'expose pas permissions_for_role nativement ; on lit les overwrites
            perms = accueil.overwrites_for(non_verif)
            _check(
                "Non vérifié → ACCUEIL visible",
                perms.view_channel is True or perms.view_channel is None,
                "(via overwrites)"
            )

        if non_verif and communaute:
            perms = communaute.overwrites_for(non_verif)
            _check(
                "Non vérifié → COMMUNAUTÉ masquée",
                perms.view_channel is False,
                "(deny attendu)"
            )

        if membre and communaute:
            perms = communaute.overwrites_for(membre)
            _check(
                "Membre → COMMUNAUTÉ accessible",
                perms.view_channel is True,
                "(allow attendu)"
            )

        if bot_principal and outils:
            perms = outils.overwrites_for(bot_principal)
            _check(
                "Antilles-OM → OUTILS ATC accessible",
                perms.view_channel is True and perms.send_messages is True,
                ""
            )

        self.report.info(
            "Tests basés sur les overwrites de catégorie. Test manuel via compte alt recommandé."
        )

    # ------------------------------------------------------------------
    # Étape 7 — Rapport final (déclenché par migrate_v2.py)
    # ------------------------------------------------------------------

    async def run_all(self) -> bool:
        ok = await self.step1_pre_checks()
        if not ok and not self.dry_run:
            self.report.alert("Pre-checks échoués — abandon.")
            return False

        await self.step2_roles()
        # Petit délai pour laisser Discord propager les rôles avant de référer aux overrides
        if not self.dry_run:
            await asyncio.sleep(2)
        await self.step3_categories()
        if not self.dry_run:
            await asyncio.sleep(1)
        await self.step4_category_permissions()
        await self.step5_channels()
        await self.step6_tests()
        return True
