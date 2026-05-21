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
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

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
CATEGORIES_CONFIG = Path(__file__).resolve().parent.parent / "config" / "categories.json"
REGIONS_CONFIG = Path(__file__).resolve().parent.parent / "utils" / "regions_panel.json"
WELCOMED_FILE = Path(__file__).resolve().parent.parent / "utils" / "presentation_welcomed.json"


def _load_welcomed() -> set[int]:
    """Charge l'ensemble des user_ids déjà accueillis dans présentation."""
    if not WELCOMED_FILE.exists():
        return set()
    try:
        data = json.loads(WELCOMED_FILE.read_text(encoding="utf-8"))
        return {int(uid) for uid in data.get("user_ids", [])}
    except (json.JSONDecodeError, ValueError):
        return set()


def _save_welcomed(welcomed: set[int]) -> None:
    WELCOMED_FILE.parent.mkdir(parents=True, exist_ok=True)
    WELCOMED_FILE.write_text(
        json.dumps({"user_ids": sorted(welcomed)}, indent=2),
        encoding="utf-8",
    )


# Mapping prédéfini pour le panneau régions/niveau aviation
# (basé sur les rôles existants du serveur)
REGIONS_PANEL_OPTIONS: list[dict] = [
    {"label": "Martinique", "emoji": "🇲🇶", "role_name": "Martinique",
     "description": "Antilles - Martinique"},
    {"label": "Guadeloupe", "emoji": "🇬🇵", "role_name": "Le Raizet",
     "description": "Antilles - Guadeloupe (Le Raizet)"},
    {"label": "Guyane", "emoji": "🇬🇫", "role_name": "Cayenne",
     "description": "Guyane - Cayenne"},
]

AVIATION_PANEL_OPTIONS: list[dict] = [
    {"label": "Débutant", "emoji": "🐣", "role_name": "Débutant",
     "description": "Je découvre l'aviation virtuelle"},
    {"label": "Pilote", "emoji": "✈️", "role_name": "Pilote",
     "description": "Je suis pilote"},
    {"label": "Contrôleur", "emoji": "🛂", "role_name": "Contrôleur",
     "description": "Je suis contrôleur ATC"},
    {"label": "AFIS", "emoji": "🎙", "role_name": "AFIS",
     "description": "Je suis agent AFIS"},
]


GOVERNANCE_ROLES = {"Directeur communauté", "Administrateur"}


def _build_role_cards() -> list[dict]:
    """Fiches de poste basées sur le cahier technique V2 (PDF interne).

    L'ordre suit la hiérarchie : gouvernance, pôles, modération, technique.
    """
    return [
        # Gouvernance
        {
            "block": "Gouvernance",
            "role_name": "Directeur communauté",
            "emoji": "👑",
            "catchphrase": "Pilotage global, arbitrage, vision",
            "mission": (
                "Définir la direction du serveur, arbitrer les décisions sensibles "
                "et porter la vision communautaire. Premier décisionnaire en cas de conflit "
                "entre staffs."
            ),
            "scope": (
                "Toutes les zones du serveur. Décisions structurelles "
                "(création/suppression de rôles, refontes, partenariats stratégiques)."
            ),
            "perms": "Administrator complet (V2 §3.1)",
            "limits": (
                "1 à 3 personnes maximum. Doit déléguer aux Responsables plutôt qu'agir "
                "à leur place."
            ),
            "profile": "Membre de confiance, vue d'ensemble, sens de la médiation.",
        },
        {
            "block": "Gouvernance",
            "role_name": "Administrateur",
            "emoji": "🛡️",
            "catchphrase": "Gestion structurelle du serveur",
            "mission": (
                "Maintenir et faire évoluer la structure technique du serveur : rôles, "
                "salons, catégories, intégrations bots, permissions."
            ),
            "scope": (
                "Configuration du serveur, gestion des bots, supervision des modérateurs, "
                "application des décisions du Directeur communauté."
            ),
            "perms": (
                "Manage Server, Manage Roles, Manage Channels, Manage Messages, "
                "Ban/Kick, View Audit Log"
            ),
            "limits": (
                "Pas d'Administrator brut (réservé au Directeur communauté). Pas plus "
                "que nécessaire pour la mission (V2 §3.1)."
            ),
            "profile": "Profil technique, organisé, rigoureux sur les permissions.",
        },

        # Pôles opérationnels
        {
            "block": "Pôle opérationnel",
            "role_name": "Responsable événements",
            "emoji": "🎉",
            "catchphrase": "Pilote l'animation du serveur",
            "mission": (
                "Organiser et animer les événements de la communauté : vols de groupe, "
                "concours, soirées thématiques, annonces d'événements."
            ),
            "scope": (
                "Salon `🎉・staff-events`, écriture validée dans `📣・annonces`, "
                "création d'events Discord, coordination avec les autres responsables."
            ),
            "perms": "Manage Events, Create Events, Mention Everyone (sur annonces)",
            "limits": (
                "Annonces publiques nécessitent validation préalable. Ne crée pas "
                "d'événements concurrents à ceux déjà planifiés."
            ),
            "profile": "Créatif, organisé, disponible pour planifier en avance.",
        },
        {
            "block": "Pôle opérationnel",
            "role_name": "Responsable aviation",
            "emoji": "✈️",
            "catchphrase": "Structure le pôle contrôle et pilote",
            "mission": (
                "Coordonner les activités ATC et pilotes : créneaux de contrôle, briefings, "
                "contenus aviation, lien avec les structures officielles IVAO."
            ),
            "scope": (
                "Salon `✈・staff-atc`, écriture dans les salons applicatifs ATC, "
                "organisation des sessions de vol et de contrôle."
            ),
            "perms": "Manage Threads, écriture dans salons ATC dédiés",
            "limits": (
                "Pas de modération générale (réservée aux Modérateurs). Pas de "
                "décisions structurelles."
            ),
            "profile": "Pilote ou contrôleur expérimenté, connaît IVAO, sens du briefing.",
        },
        {
            "block": "Pôle opérationnel",
            "role_name": "Responsable communauté",
            "emoji": "🤝",
            "catchphrase": "Suit la vie du serveur hors modération",
            "mission": (
                "Veiller à l'ambiance, intégrer les nouveaux réguliers, faire remonter "
                "les idées et suggestions, fluidifier la vie communautaire."
            ),
            "scope": (
                "Salons de la catégorie `💬 ▸ COMMUNAUTÉ`, `💡・suggestions`, "
                "interactions avec les Helpers pour l'onboarding."
            ),
            "perms": "Manage Messages (ciblé), Manage Threads",
            "limits": (
                "N'est pas un modérateur — pas de sanctions. Travaille en lien avec "
                "Helper et Responsable accueil."
            ),
            "profile": "Sociable, à l'écoute, présent régulièrement sur le serveur.",
        },
        {
            "block": "Pôle opérationnel",
            "role_name": "Responsable documentation",
            "emoji": "📚",
            "catchphrase": "Tient à jour la base documentaire",
            "mission": (
                "Maintenir les docs aviation, la phraséologie, les NOTAMs et la structure "
                "informationnelle du serveur. Améliorer la qualité perçue de la documentation."
            ),
            "scope": (
                "Catégorie `📚 ▸ DOCUMENTATION` (martinique-guadeloupe, piarco-fir, "
                "guyane, afis, ivao-phraséologie, notams-updates) et `🔧・changelog`."
            ),
            "perms": (
                "Send Messages, Manage Messages, Manage Threads, Manage Webhooks "
                "dans la documentation"
            ),
            "limits": (
                "Modifications majeures soumises à validation. Pas de modification "
                "des règles du serveur."
            ),
            "profile": "Méthodique, soucieux du détail, à l'aise avec les sources IVAO.",
        },
        {
            "block": "Pôle opérationnel",
            "role_name": "Responsable partenariats",
            "emoji": "🤝",
            "catchphrase": "Gère les liens externes validés",
            "mission": (
                "Identifier, négocier et entretenir les partenariats avec d'autres "
                "communautés ou structures aviation. Valoriser les collaborations."
            ),
            "scope": (
                "Salon `🤝・partenaires`, écriture dans annonces selon validation, "
                "communication externe au nom du serveur."
            ),
            "perms": "Manage Webhooks, Create Instant Invite",
            "limits": (
                "Toute mise en avant nécessite validation du Directeur communauté. "
                "Pas d'engagements financiers sans accord."
            ),
            "profile": "Bon relationnel, fiable dans ses engagements.",
        },

        # Modération
        {
            "block": "Modération",
            "role_name": "Modérateur",
            "emoji": "🔨",
            "catchphrase": "Modération de la communauté",
            "mission": (
                "Faire respecter le règlement, gérer les incidents, sanctionner les "
                "comportements problématiques, intervenir dans les conflits."
            ),
            "scope": (
                "Ensemble des salons publics. Salon `🔨・staff-modération` pour la "
                "coordination interne."
            ),
            "perms": (
                "Timeout, Kick, Ban, Manage Messages, Move Members, Mute/Deafen, "
                "View Audit Log"
            ),
            "limits": (
                "Pas de Manage Server (V2 §3.3). Décisions de ban prolongé soumises "
                "à validation collégiale."
            ),
            "profile": "Calme sous pression, juste, capable de désamorcer un conflit.",
        },
        {
            "block": "Modération",
            "role_name": "Helper",
            "emoji": "🙋",
            "catchphrase": "Accueil, aide, orientation, tickets simples",
            "mission": (
                "Accueillir les nouveaux membres, répondre aux questions de base, "
                "traiter les tickets simples, orienter vers les bonnes ressources."
            ),
            "scope": (
                "Tickets de support général, salons d'accueil, questions/aide. "
                "Premier point de contact pour les nouveaux."
            ),
            "perms": "Manage Messages (léger), Timeout léger, Move Members, Manage Threads",
            "limits": (
                "Pas de Kick/Ban. Pas de permissions structurelles. "
                "Escalade les cas complexes vers Modérateur."
            ),
            "profile": "Patient, pédagogue, disponible.",
        },
        {
            "block": "Modération",
            "role_name": "Responsable accueil",
            "emoji": "👋",
            "catchphrase": "Première ligne d'intégration des nouveaux",
            "mission": (
                "Superviser le parcours d'accueil, valider les présentations, fluidifier "
                "le passage `Non vérifié` → `Membre` quand nécessaire."
            ),
            "scope": (
                "Catégorie `👋 ▸ ACCUEIL`, supervision des Helpers, suivi du système "
                "de validation du règlement."
            ),
            "perms": "Kick, Ban, Manage Messages, Move Members, Mute/Deafen",
            "limits": (
                "Pas de modération générale en dehors de l'accueil. Travaille en lien "
                "avec les Helpers."
            ),
            "profile": "Accueillant, organisé, sait gérer un afflux de nouveaux.",
        },

        # Technique / Bots
        {
            "block": "Technique",
            "role_name": "Antilles - Outre Mer",
            "emoji": "🤖",
            "catchphrase": "Bot principal du serveur",
            "mission": (
                "Faire tourner l'écosystème automatisé : tickets, accueil, panneaux "
                "régions, stats ATC, booking, METAR, monitoring."
            ),
            "scope": "Toutes les opérations automatisées du serveur.",
            "perms": "Administrator (exception V2 §3.4 — le code l'exige réellement)",
            "limits": (
                "Doit rester au-dessus des rôles qu'il gère. Modifications du bot "
                "uniquement par l'équipe technique."
            ),
            "profile": "Pas humain.",
        },
        {
            "block": "Communauté",
            "role_name": "Membre",
            "emoji": "🌴",
            "catchphrase": "Rôle pivot d'accès au serveur",
            "mission": (
                "Participer activement à la vie du serveur dans les salons communautaires, "
                "vocaux, et applicatifs."
            ),
            "scope": (
                "Toutes les catégories publiques (Communauté, Informations, Outils ATC, "
                "Support, Documentation)."
            ),
            "perms": (
                "Lecture/écriture dans communauté, vocaux complets (soundboard, "
                "voice messages, activités, streaming), réactions, threads"
            ),
            "limits": "Pas d'accès au Staff ni à Fly Tropik (réservé TPK).",
            "profile": "Toute personne ayant accepté le règlement.",
        },
        {
            "block": "Communauté",
            "role_name": "Non vérifié",
            "emoji": "🚪",
            "catchphrase": "Sas d'entrée du serveur",
            "mission": "État transitoire avant validation du règlement.",
            "scope": "Catégorie `👋 ▸ ACCUEIL` + `🎫 ▸ SUPPORT` uniquement.",
            "perms": "Lecture des règles, écriture dans présentation, ouverture de tickets",
            "limits": "Aucun accès aux salons communautaires tant que pas validé.",
            "profile": "Tout nouveau membre arrivant sur le serveur (auto-attribué).",
        },
    ]





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
    # /structure apply-target
    # ------------------------------------------------------------------
    # Commande "tout-en-un" : renomme les salons selon target, réécrit les
    # overrides catégorie, synchronise tous les salons enfants, applique les
    # overrides spécifiques de salon.

    @structure.command(
        name="apply-target",
        description="Applique le v2_target.json complet : renames + permissions",
    )
    @require_governance()
    async def apply_target(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        target = load_target()
        role_by_name: dict[str, discord.Role] = {r.name: r for r in guild.roles}

        def resolve(ref: str):
            if ref == "@everyone":
                return guild.default_role
            return role_by_name.get(ref)

        stats = {"cats_renamed": 0, "channels_renamed": 0, "cats_synced": 0,
                 "channels_synced": 0, "ch_overrides": 0, "errors": 0}
        errors: list[str] = []

        for cat_spec in target.get("categories", []):
            cat_name = cat_spec.get("name")
            cat = None
            if cat_spec.get("existing_id"):
                cat = guild.get_channel(int(cat_spec["existing_id"]))
                if not isinstance(cat, discord.CategoryChannel):
                    cat = None
            if cat is None and cat_spec.get("old_name"):
                cat = discord.utils.get(guild.categories, name=cat_spec["old_name"])
            if cat is None:
                cat = discord.utils.get(guild.categories, name=cat_name)
            if cat is None:
                errors.append(f"Cat introuvable: {cat_name}")
                stats["errors"] += 1
                continue

            # 1. Renommer la catégorie si besoin
            if cat.name != cat_name:
                try:
                    await cat.edit(name=cat_name, reason="apply-target — rename cat")
                    stats["cats_renamed"] += 1
                except discord.Forbidden:
                    errors.append(f"Refus rename cat: {cat.name}")
                    stats["errors"] += 1

            # 2. Renommer les salons cibles si besoin
            for ch_spec in cat_spec.get("channels", []):
                target_ch_name = ch_spec.get("name")
                ch = None
                if ch_spec.get("existing_id"):
                    ch = guild.get_channel(int(ch_spec["existing_id"]))
                if ch is None:
                    continue
                if ch.name != target_ch_name:
                    try:
                        await ch.edit(name=target_ch_name,
                                      reason="apply-target — rename salon")
                        stats["channels_renamed"] += 1
                    except discord.Forbidden:
                        errors.append(f"Refus rename salon: {ch.name}")
                        stats["errors"] += 1

            # 3. Réécrire entièrement les overrides de la catégorie
            cat_overwrites: dict = {}
            for ref, spec in cat_spec.get("overrides", {}).items():
                tgt = resolve(ref)
                if tgt is None:
                    errors.append(f"Override cat `{cat_name}` : rôle `{ref}` introuvable")
                    continue
                cat_overwrites[tgt] = perm_dict_to_overwrite(
                    spec.get("allow", []), spec.get("deny", [])
                )
            try:
                await cat.edit(overwrites=cat_overwrites,
                               reason="apply-target — overrides catégorie")
                stats["cats_synced"] += 1
            except discord.Forbidden:
                errors.append(f"Refus overrides cat: {cat_name}")
                stats["errors"] += 1
                continue
            except discord.HTTPException as e:
                if getattr(e, "code", None) == 350005:
                    errors.append(
                        f"Cat `{cat_name}` : Onboarding Discord bloque (désactive-le dans "
                        f"Paramètres serveur → Onboarding)"
                    )
                else:
                    errors.append(f"HTTP overrides cat `{cat_name}`: {e}")
                stats["errors"] += 1
                continue

            # 4. Sync TOUS les salons enfants sur la cat (héritage propre)
            for ch in cat.channels:
                try:
                    await ch.edit(sync_permissions=True,
                                  reason="apply-target — sync sur cat")
                    stats["channels_synced"] += 1
                except discord.Forbidden:
                    errors.append(f"Refus sync salon: {ch.name}")
                    stats["errors"] += 1
                except discord.HTTPException as e:
                    errors.append(f"HTTP sync {ch.name}: {e}")
                    stats["errors"] += 1

            # 5. Réappliquer overrides spécifiques de salon (après sync)
            for ch_spec in cat_spec.get("channels", []):
                if not ch_spec.get("overrides"):
                    continue
                ch = None
                if ch_spec.get("existing_id"):
                    ch = guild.get_channel(int(ch_spec["existing_id"]))
                if ch is None:
                    ch = discord.utils.get(cat.channels, name=ch_spec["name"])
                if ch is None:
                    continue
                for ref, spec in ch_spec["overrides"].items():
                    tgt = resolve(ref)
                    if tgt is None:
                        continue
                    ow = perm_dict_to_overwrite(spec.get("allow", []), spec.get("deny", []))
                    try:
                        await ch.set_permissions(tgt, overwrite=ow,
                                                 reason="apply-target — override salon")
                        stats["ch_overrides"] += 1
                    except discord.Forbidden:
                        errors.append(f"Refus override {ch.name}/{ref}")
                        stats["errors"] += 1

        lines = [
            "✅ **apply-target terminé**",
            f"• Catégories renommées : {stats['cats_renamed']}",
            f"• Salons renommés : {stats['channels_renamed']}",
            f"• Catégories overrides MAJ : {stats['cats_synced']}",
            f"• Salons synchronisés sur cat : {stats['channels_synced']}",
            f"• Overrides salon réappliqués : {stats['ch_overrides']}",
        ]
        if errors:
            lines.append(f"\n⚠️ **Erreurs ({stats['errors']})** :")
            for e in errors[:15]:
                lines.append(f"• {e}")
            if len(errors) > 15:
                lines.append(f"… et {len(errors) - 15} de plus")
        text = "\n".join(lines)
        if len(text) <= 1900:
            await interaction.followup.send(text, ephemeral=True)
        else:
            buf = io.BytesIO(text.encode("utf-8"))
            await interaction.followup.send(
                "Rapport long, fichier joint.",
                file=discord.File(buf, filename="apply_target.md"),
                ephemeral=True,
            )

    # ------------------------------------------------------------------
    # /structure resync-permissions
    # ------------------------------------------------------------------

    @structure.command(
        name="resync-permissions",
        description="Réapplique les overrides V2 sur catégories + tous leurs salons",
    )
    @require_governance()
    async def resync_permissions(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        target = load_target()

        # Build name → role map pour résoudre les overrides du target
        role_by_name: dict[str, discord.Role] = {r.name: r for r in guild.roles}

        def resolve(ref: str):
            if ref == "@everyone":
                return guild.default_role
            return role_by_name.get(ref)

        stats = {"cats_synced": 0, "channels_synced": 0, "ch_overrides": 0, "errors": 0}
        errors: list[str] = []

        for cat_spec in target.get("categories", []):
            cat_name = cat_spec.get("name")
            cat = None
            if cat_spec.get("existing_id"):
                cat = guild.get_channel(int(cat_spec["existing_id"]))
                if not isinstance(cat, discord.CategoryChannel):
                    cat = None
            if cat is None:
                cat = discord.utils.get(guild.categories, name=cat_name)
            if cat is None:
                errors.append(f"Cat introuvable: {cat_name}")
                stats["errors"] += 1
                continue

            # 1. Réécrire entièrement les overrides de la catégorie
            cat_overwrites: dict = {}
            for ref, spec in cat_spec.get("overrides", {}).items():
                tgt = resolve(ref)
                if tgt is None:
                    continue
                cat_overwrites[tgt] = perm_dict_to_overwrite(
                    spec.get("allow", []), spec.get("deny", [])
                )
            try:
                await cat.edit(overwrites=cat_overwrites,
                               reason="Resync V2 — overrides catégorie")
                stats["cats_synced"] += 1
            except discord.Forbidden:
                errors.append(f"Refus cat: {cat_name}")
                stats["errors"] += 1
                continue

            # 2. Sync TOUS les salons enfants de la cat (V2 ou non) sur la cat
            #    → tout salon dans une cat V2 hérite proprement des perms V2
            for ch in cat.channels:
                try:
                    await ch.edit(sync_permissions=True,
                                  reason="Resync V2 — héritage catégorie")
                    stats["channels_synced"] += 1
                except discord.Forbidden:
                    errors.append(f"Refus sync salon: {ch.name}")
                    stats["errors"] += 1
                except discord.HTTPException as e:
                    errors.append(f"Erreur sync {ch.name}: {e}")
                    stats["errors"] += 1

            # 3. Pour les salons V2 avec overrides spécifiques → les réappliquer après sync
            for ch_spec in cat_spec.get("channels", []):
                if not ch_spec.get("overrides"):
                    continue
                ch_id = ch_spec.get("existing_id")
                ch = None
                if ch_id:
                    ch = guild.get_channel(int(ch_id))
                if ch is None:
                    ch = discord.utils.get(cat.channels, name=ch_spec["name"])
                if ch is None:
                    continue
                for ref, spec in ch_spec["overrides"].items():
                    tgt = resolve(ref)
                    if tgt is None:
                        continue
                    ow = perm_dict_to_overwrite(spec.get("allow", []), spec.get("deny", []))
                    try:
                        await ch.set_permissions(tgt, overwrite=ow,
                                                 reason="Resync V2 — override salon")
                        stats["ch_overrides"] += 1
                    except discord.Forbidden:
                        errors.append(f"Refus override {ch.name}/{ref}")
                        stats["errors"] += 1

        lines = [
            "✅ **Resync permissions terminé**",
            f"• Catégories synchronisées : {stats['cats_synced']}",
            f"• Salons synchronisés : {stats['channels_synced']}",
            f"• Overrides salon réappliqués : {stats['ch_overrides']}",
        ]
        if errors:
            lines.append(f"\n⚠️ Erreurs ({stats['errors']}) :")
            for e in errors[:10]:
                lines.append(f"• {e}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

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

    # ------------------------------------------------------------------
    # Onboarding V2 : auto-attribution du rôle Non vérifié au join
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Détecte les présentations dans 📚・présentation et accueille avec un embed.

        Le message du membre reste intact. Le bot ajoute une réaction 👋 et
        poste un embed de bienvenue qui disparaît après 60 secondes pour
        éviter de polluer le salon.
        """
        if message.author.bot:
            return
        if message.guild is None:
            return
        # Cible par ID ou par nom (présentation V2)
        ch_name = message.channel.name if hasattr(message.channel, "name") else ""
        if "présentation" not in ch_name:
            return

        # Ne pas accueillir si l'utilisateur a déjà été accueilli (1re fois only).
        # Sécurité supplémentaire : vérifier l'historique du salon pour les
        # membres existants avant migration (file vide mais ils ont déjà posté).
        welcomed = _load_welcomed()
        if message.author.id in welcomed:
            return

        # Vérif historique : si le membre a déjà posté avant ce message,
        # c'est qu'il était là avant et on doit pas l'accueillir.
        already_posted = False
        try:
            async for hist in message.channel.history(limit=200, before=message):
                if hist.author.id == message.author.id:
                    already_posted = True
                    break
        except discord.HTTPException:
            pass

        # Marquer comme accueilli quoi qu'il arrive (pour le futur)
        welcomed.add(message.author.id)
        _save_welcomed(welcomed)

        if already_posted:
            # Le membre était déjà présent avant — pas de message de bienvenue
            return

        try:
            await message.add_reaction("👋")
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title=f"👋 Bienvenue {message.author.display_name} !",
            description=(
                f"Merci pour ta présentation, {message.author.mention} ! "
                f"La communauté **Antilles - Outre Mer** est ravie de t'accueillir. 🌴\n\n"
                f"**Prochaines étapes** :\n"
                f"• Si pas encore fait : accepte le règlement pour devenir `Membre`\n"
                f"• Choisis ta région et ton profil aviation dans `📜・règlement`\n"
                f"• Découvre les salons communautaires dans `💬 ▸ COMMUNAUTÉ`\n"
                f"• Pour les vols et ATC : `🛠️ ▸ OUTILS ATC / BOT`\n\n"
                f"Si tu as la moindre question, ouvre un ticket dans `🎫 ▸ SUPPORT`. ✈️"
            ),
            color=discord.Color.from_rgb(28, 168, 102),
        )
        embed.set_footer(text="Ce message disparaîtra dans 60 secondes")
        try:
            reply = await message.channel.send(embed=embed)
            await asyncio.sleep(60)
            await reply.delete()
        except (discord.HTTPException, discord.Forbidden):
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Attribue automatiquement Non vérifié aux nouveaux membres.

        Sans ce listener, les nouveaux n'ont aucun rôle et @everyone est deny
        partout — donc serveur invisible. Ce listener garantit qu'ils ont au
        moins accès à 👋 ▸ ACCUEIL pour accepter le règlement.
        """
        if member.bot:
            return
        non_verifie = discord.utils.get(member.guild.roles, name="Non vérifié")
        if non_verifie is None:
            return
        if non_verifie in member.roles:
            return
        try:
            await member.add_roles(non_verifie, reason="Auto-assign à l'arrivée (V2)")
        except discord.Forbidden:
            pass

    @structure.command(
        name="setup-onboarding-flow",
        description="Setup complet: supprime l'ancien panneau, poste règlement + panneau régions",
    )
    @app_commands.describe(channel="Salon où poster le flow (typiquement #📜・règlement)")
    @require_governance()
    async def setup_onboarding_flow(self, interaction: discord.Interaction,
                                     channel: discord.TextChannel) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        report: list[str] = ["## 🎯 Setup onboarding flow", ""]

        # 1. Supprimer l'ancien panneau régions si présent
        if REGIONS_CONFIG.exists():
            try:
                old_cfg = json.loads(REGIONS_CONFIG.read_text(encoding="utf-8"))
                old_ch_id = int(old_cfg.get("channel_id", 0))
                old_msg_id = int(old_cfg.get("message_id", 0))
                if old_ch_id and old_msg_id:
                    old_ch = guild.get_channel(old_ch_id)
                    if isinstance(old_ch, discord.TextChannel):
                        try:
                            old_msg = await old_ch.fetch_message(old_msg_id)
                            await old_msg.delete()
                            report.append(f"• 🗑️ Ancien panneau régions supprimé (msg `{old_msg_id}`)")
                        except (discord.NotFound, discord.Forbidden):
                            report.append(f"• ℹ️ Ancien panneau introuvable ou déjà supprimé")
            except Exception:
                pass

        # 2. Poster le bouton règlement (sera EN HAUT du flow)
        rules_embed = discord.Embed(
            title="📜 Validation du règlement",
            description=(
                "Pour accéder à l'ensemble du serveur, **lis le règlement ci-dessus** "
                "puis clique sur le bouton **« ✅ J'accepte le règlement »** ci-dessous.\n\n"
                "Tu recevras alors le rôle `Membre`. **Pense aussi à te présenter** "
                "dans le salon `📚・présentation` et à choisir ta région + ton profil "
                "aviation dans le panneau juste en dessous. ✈️🌴"
            ),
            color=discord.Color.from_rgb(28, 168, 102),
        )
        rules_embed.set_footer(text="Une seule validation suffit · 🌴 Antilles - OM")
        try:
            rules_msg = await channel.send(embed=rules_embed, view=AcceptRulesView())
            report.append(f"• ✅ Bouton règlement posté (msg `{rules_msg.id}`)")
        except discord.Forbidden:
            report.append("• ❌ Permission refusée pour poster")
            await interaction.followup.send("\n".join(report), ephemeral=True)
            return

        # 3. Poster le panneau régions/aviation (EN DESSOUS)
        regions_embed = discord.Embed(
            title="🌎 Choisis ton profil",
            description=(
                "**Une fois ton règlement validé** ci-dessus, sélectionne ici "
                "**ta région d'origine** et **ton profil aviation**.\n\n"
                "*Les rôles sont attribués/retirés en cliquant sur l'option.*"
            ),
            color=discord.Color.from_rgb(28, 168, 102),
        )
        regions_embed.set_footer(text="🌴 Les Antilles - OM 🌴 • V2")
        try:
            regions_msg = await channel.send(embed=regions_embed, view=RegionsPanelView(guild=guild))
            report.append(f"• ✅ Panneau régions/aviation posté (msg `{regions_msg.id}`)")
            # Sauvegarde pour pouvoir le supprimer/recréer plus tard
            REGIONS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            REGIONS_CONFIG.write_text(json.dumps({
                "channel_id": str(channel.id),
                "rules_message_id": str(rules_msg.id),
                "message_id": str(regions_msg.id),
                "updated_at": datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
        except discord.Forbidden:
            report.append("• ❌ Permission refusée pour le panneau régions")

        report.append("")
        report.append(f"✅ Flow setup dans {channel.mention} : règlement → régions/aviation")
        await interaction.followup.send("\n".join(report), ephemeral=True)

    @structure.command(
        name="post-rules-button",
        description="Poste un bouton 'J'accepte le règlement' (persistant) dans un salon",
    )
    @app_commands.describe(
        channel="Salon où poster (typiquement #📜・règlement)",
        title="Titre de l'embed (optionnel)",
    )
    @require_governance()
    async def post_rules_button(self, interaction: discord.Interaction,
                                 channel: discord.TextChannel,
                                 title: Optional[str] = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        embed = discord.Embed(
            title=title or "📜 Validation du règlement",
            description=(
                "Pour accéder à l'ensemble du serveur, **lis le règlement ci-dessus** "
                "puis clique sur le bouton **« J'accepte le règlement »** ci-dessous.\n\n"
                "Tu recevras alors le rôle `Membre`. **Pense aussi à te présenter** "
                "dans le salon `📚・présentation` et à choisir ta région + ton profil "
                "aviation. ✈️🌴"
            ),
            color=discord.Color.from_rgb(28, 168, 102),
        )
        embed.set_footer(text="Une seule validation suffit · Bot Antilles - OM")
        view = AcceptRulesView()
        try:
            msg = await channel.send(embed=embed, view=view)
            await interaction.followup.send(
                f"✅ Bouton posté dans {channel.mention} (msg `{msg.id}`).\n"
                f"Le bouton reste persistant même après redémarrage du bot.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Permission refusée pour poster dans ce salon.", ephemeral=True
            )

    @structure.command(
        name="onboard-existing",
        description="Attribue Non vérifié à tous les membres qui n'ont aucun rôle d'accès",
    )
    @require_governance()
    async def onboard_existing(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        non_verifie = discord.utils.get(guild.roles, name="Non vérifié")
        membre = discord.utils.get(guild.roles, name="Membre")
        if non_verifie is None or membre is None:
            await interaction.followup.send(
                "❌ Rôles `Non vérifié` ou `Membre` introuvables.", ephemeral=True
            )
            return

        # Rôles qui donnent accès au serveur (membre validé OU staff/protégé)
        access_role_names = {
            "Membre", "Non vérifié",
            "Modérateur", "Helper", "Responsable accueil",
            "Responsable événements", "Responsable aviation",
            "Responsable communauté", "Responsable documentation",
            "Responsable partenariats",
            "Administrateur", "Directeur communauté",
            "Super-Admin", ".\\",
        }

        assigned = 0
        skipped_bots = 0
        for m in guild.members:
            if m.bot:
                skipped_bots += 1
                continue
            if any(r.name in access_role_names for r in m.roles):
                continue
            try:
                await m.add_roles(non_verifie, reason="Onboarding rétroactif V2")
                assigned += 1
            except discord.Forbidden:
                pass

        await interaction.followup.send(
            f"✅ **{assigned} membres** ont reçu `Non vérifié`.\n"
            f"(Bots ignorés : {skipped_bots})",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /structure finalize  +  /structure cleanup-archive
    # ------------------------------------------------------------------

    @structure.command(
        name="post-role-cards",
        description="Poste les fiches de poste de tous les rôles V2 (selon cahier technique)",
    )
    @app_commands.describe(channel="Salon où poster les fiches (typiquement #💬・staff-général)")
    @require_governance()
    async def post_role_cards(self, interaction: discord.Interaction,
                               channel: discord.TextChannel) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild

        cards = _build_role_cards()

        # Message d'intro
        intro = discord.Embed(
            title="📋 Fiches de poste — Rôles V2",
            description=(
                "Vous trouverez ci-dessous **les fiches de poste** des rôles du serveur "
                "selon le cahier technique V2.\n\n"
                "Chaque fiche décrit la mission, le périmètre d'action, les permissions "
                "clés et les limites du rôle. Référez-vous y en cas de doute sur "
                "qui fait quoi."
            ),
            color=discord.Color.from_rgb(28, 168, 102),
        )
        intro.set_footer(text="🌴 Antilles - OM • Refonte V2")
        try:
            await channel.send(embed=intro)
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission refusée.", ephemeral=True)
            return

        posted = 0
        for card in cards:
            role = discord.utils.get(guild.roles, name=card["role_name"])
            color = role.color if role and role.color.value != 0 else discord.Color.dark_grey()

            embed = discord.Embed(
                title=f"{card['emoji']} {card['role_name']}",
                description=f"*{card['catchphrase']}*",
                color=color,
            )
            embed.add_field(name="🎯 Mission", value=card["mission"], inline=False)
            embed.add_field(name="🗂️ Périmètre", value=card["scope"], inline=False)
            embed.add_field(name="🔑 Permissions clés", value=card["perms"], inline=False)
            if card.get("limits"):
                embed.add_field(name="🚫 Limites", value=card["limits"], inline=False)
            if card.get("profile"):
                embed.add_field(name="👤 Profil", value=card["profile"], inline=False)
            embed.set_footer(text=f"Bloc : {card['block']}")
            try:
                await channel.send(embed=embed)
                posted += 1
                await asyncio.sleep(0.7)  # rate limit gentil
            except discord.Forbidden:
                break

        await interaction.followup.send(
            f"✅ **{posted} fiches de poste** postées dans {channel.mention}.",
            ephemeral=True,
        )

    @structure.command(
        name="finalize",
        description="Patch main.py + Directeur communauté + panneau régions",
    )
    @app_commands.describe(regions_channel="Salon où poster le panneau de sélection")
    @require_governance()
    async def finalize_cmd(self, interaction: discord.Interaction,
                            regions_channel: discord.TextChannel) -> None:
        await _do_finalize(interaction, regions_channel)

    @structure.command(
        name="cleanup-archive",
        description="Supprime les salons résiduels de _archive (avec confirmation)",
    )
    @require_governance()
    async def cleanup_archive_cmd(self, interaction: discord.Interaction) -> None:
        await _do_cleanup_archive(interaction)


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


def _save_categories_config(replacements: dict[str, int]) -> dict:
    """Sauvegarde les IDs de catégorie dans config/categories.json.

    main.py lit ce fichier au démarrage pour override ATC_CATEGORY_ID +
    SUPPORT_CATEGORY_ID. Ce mécanisme survit aux `git reset --hard` du
    container Pterodactyl (le fichier est en gitignore).

    Retourne {var_name: (old_value, new_value)}.
    """
    existing: dict = {}
    if CATEGORIES_CONFIG.exists():
        try:
            existing = json.loads(CATEGORIES_CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    changes: dict[str, tuple[int, int]] = {}
    for var, new_val in replacements.items():
        old_val = int(existing.get(var, 0)) if existing.get(var) else None
        if old_val == new_val:
            continue
        existing[var] = str(new_val)
        changes[var] = (old_val or 0, new_val)

    if changes:
        CATEGORIES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        existing["_updated_at"] = datetime.now().isoformat()
        CATEGORIES_CONFIG.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return changes


async def _do_finalize(interaction: discord.Interaction,
                       regions_channel: discord.TextChannel) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        report: list[str] = ["## 🏁 Finalisation V2", ""]

        # 1. Récupérer les IDs des cats cibles
        outils_atc = discord.utils.get(guild.categories, name="🛠️ ▸ OUTILS ATC / BOT")
        support = discord.utils.get(guild.categories, name="🎫 ▸ SUPPORT")
        documentation = discord.utils.get(guild.categories, name="📚 ▸ DOCUMENTATION")
        staff = discord.utils.get(guild.categories, name="🛡️ ▸ STAFF")

        report.append("### 1️⃣ Catégories détectées")
        for label, cat in [("OUTILS ATC", outils_atc), ("SUPPORT", support),
                           ("DOCUMENTATION", documentation), ("STAFF", staff)]:
            if cat:
                report.append(f"• {label} : `{cat.id}`")
            else:
                report.append(f"• {label} : ❌ introuvable")
        report.append("")

        # 2. Patch main.py
        replacements = {}
        if outils_atc:
            replacements["ATC_CATEGORY_ID"] = outils_atc.id
        if support:
            replacements["SUPPORT_CATEGORY_ID"] = support.id

        report.append("### 2️⃣ Sauvegarde IDs dans config/categories.json")
        if replacements:
            try:
                changes = _save_categories_config(replacements)
                if changes:
                    for var, (old, new) in changes.items():
                        report.append(f"• `{var}` : `{old}` → `{new}` ✓")
                    report.append("> ⚠️ Restart Pterodactyl requis pour que main.py lise le nouveau fichier")
                else:
                    report.append("• IDs déjà à jour, aucun changement")
            except Exception as e:
                report.append(f"❌ Erreur sauvegarde : {e}")
        else:
            report.append("• Aucune catégorie cible détectée, skip")
        report.append("")

        # 3. Auto-attribuer Directeur communauté
        report.append("### 3️⃣ Rôle Directeur communauté")
        director = discord.utils.get(guild.roles, name="Directeur communauté")
        if director is None:
            report.append("• ❌ Rôle introuvable")
        elif director in interaction.user.roles:
            report.append(f"• {interaction.user.mention} a déjà le rôle ✓")
        else:
            try:
                await interaction.user.add_roles(director, reason="Finalize V2")
                report.append(f"• {interaction.user.mention} → {director.mention} attribué ✓")
            except discord.Forbidden:
                report.append("• ❌ Permission refusée (hiérarchie du bot ?)")
        report.append("")

        # 4. Poster le panneau régions
        report.append(f"### 4️⃣ Panneau régions/aviation dans {regions_channel.mention}")
        embed = discord.Embed(
            title="🌎 Choisis ton profil",
            description=(
                "Sélectionne dans les menus ci-dessous **ta région d'origine** "
                "et **ton profil aviation**.\n\n"
                "*Les rôles sont attribués/retirés en cliquant sur l'option.*"
            ),
            color=discord.Color.from_rgb(28, 168, 102),
        )
        embed.set_footer(text="🌴 Les Antilles - OM 🌴 • V2")
        view = RegionsPanelView(guild=guild)
        try:
            msg = await regions_channel.send(embed=embed, view=view)
            report.append(f"• Panneau posté (msg `{msg.id}`) ✓")
            # Sauvegarder pour référence
            try:
                REGIONS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
                REGIONS_CONFIG.write_text(
                    json.dumps({"channel_id": str(regions_channel.id),
                                "message_id": str(msg.id),
                                "created_at": datetime.now().isoformat()},
                               indent=2), encoding="utf-8")
            except Exception:
                pass
        except discord.Forbidden:
            report.append("• ❌ Permission refusée pour poster dans ce salon")

        text = "\n".join(report)
        if len(text) <= 1900:
            await interaction.followup.send(text, ephemeral=True)
        else:
            buf = io.BytesIO(text.encode("utf-8"))
            await interaction.followup.send(
                "Rapport long, fichier joint.",
                file=discord.File(buf, filename="finalize.md"),
                ephemeral=True,
            )

async def _do_cleanup_archive(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        archive = discord.utils.get(guild.categories, name="🗄️ ▸ _archive")
        if archive is None:
            await interaction.followup.send("❌ Catégorie `_archive` introuvable.", ephemeral=True)
            return
        if not archive.channels:
            await interaction.followup.send("ℹ️ `_archive` est vide.", ephemeral=True)
            return

        listing = "\n".join(f"• `{ch.name}` ({ch.type})" for ch in archive.channels)
        embed = discord.Embed(
            title="⚠️ Confirmation suppression _archive",
            description=(
                f"Tu es sur le point de **SUPPRIMER DÉFINITIVEMENT** "
                f"{len(archive.channels)} salons :\n\n{listing}\n\n"
                f"Cette action est **irréversible**."
            ),
            color=discord.Color.red(),
        )
        view = ConfirmArchiveCleanupView(interaction.user.id, archive)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class ConfirmArchiveCleanupView(discord.ui.View):
    def __init__(self, requester_id: int, archive: discord.CategoryChannel) -> None:
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.archive = archive
        self.handled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Pas pour toi.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Supprimer tout", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction, button):
        if self.handled:
            return
        self.handled = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="🗑️ Suppression en cours…", view=self)
        deleted = 0
        failed: list[str] = []
        for ch in list(self.archive.channels):
            try:
                await ch.delete(reason="Cleanup archive V2")
                deleted += 1
            except discord.Forbidden:
                failed.append(ch.name)
        try:
            if not self.archive.channels:
                await self.archive.delete(reason="Cleanup archive V2 — cat vide")
                cat_msg = " + catégorie `_archive` supprimée"
            else:
                cat_msg = ""
        except discord.Forbidden:
            cat_msg = ""
        msg = f"✅ {deleted} salons supprimés{cat_msg}."
        if failed:
            msg += f"\n⚠️ Refus : {', '.join(failed)}"
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction, button):
        self.handled = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="❌ Annulé.", view=self)


class SelfAssignSelect(discord.ui.Select):
    """Menu déroulant persistant : attribue/retire un rôle à l'utilisateur."""

    def __init__(self, custom_id: str, placeholder: str, options_spec: list[dict],
                 role_ids: dict[str, int]) -> None:
        opts = []
        for spec in options_spec:
            rid = role_ids.get(spec["role_name"])
            if rid is None:
                continue
            opts.append(discord.SelectOption(
                label=spec["label"],
                value=str(rid),
                emoji=spec["emoji"],
                description=spec.get("description", "")[:100],
            ))
        super().__init__(
            placeholder=placeholder,
            options=opts or [discord.SelectOption(label="Aucun rôle disponible", value="0")],
            custom_id=custom_id,
            min_values=0,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values or self.values[0] == "0":
            await interaction.response.send_message("Aucune sélection.", ephemeral=True)
            return
        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        member = interaction.user
        if role in member.roles:
            await member.remove_roles(role, reason="Self-assign via panel")
            await interaction.response.send_message(
                f"➖ Rôle {role.mention} retiré.", ephemeral=True
            )
        else:
            await member.add_roles(role, reason="Self-assign via panel")
            await interaction.response.send_message(
                f"✅ Rôle {role.mention} attribué.", ephemeral=True
            )


class AcceptRulesView(discord.ui.View):
    """View persistante : bouton 'J'accepte le règlement' → Non vérifié → Membre."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="J'accepte le règlement",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="structure:accept_rules",
    )
    async def accept(self, interaction: discord.Interaction,
                     button: discord.ui.Button) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Erreur interne.", ephemeral=True
            )
            return
        guild = interaction.guild
        non_verifie = discord.utils.get(guild.roles, name="Non vérifié")
        membre = discord.utils.get(guild.roles, name="Membre")
        if membre is None:
            await interaction.response.send_message(
                "❌ Rôle `Membre` introuvable. Contacte le staff.", ephemeral=True
            )
            return
        if membre in member.roles:
            await interaction.response.send_message(
                "ℹ️ Tu es déjà validé en tant que `Membre`. Bienvenue !",
                ephemeral=True,
            )
            return
        try:
            await member.add_roles(membre, reason="Acceptation du règlement V2")
            if non_verifie and non_verifie in member.roles:
                await member.remove_roles(non_verifie, reason="Acceptation du règlement V2")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Permission refusée. Contacte un admin.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ **Bienvenue {member.mention} !**\n"
            f"Tu as accepté le règlement et obtenu le rôle `Membre`. "
            f"Tu as maintenant accès à l'ensemble du serveur.\n\n"
            f"**Pour bien démarrer :**\n"
            f"• 🌎 Choisis ta région et ton profil aviation sur le panneau juste en dessous\n"
            f"• 📚 Présente-toi à la communauté dans `📚・présentation`\n"
            f"• 💬 Viens dire bonjour dans `💬・général`\n\n"
            f"Bons vols ! ✈️🌴",
            ephemeral=True,
        )


class RegionsPanelView(discord.ui.View):
    """View persistante pour le panneau régions + niveau aviation."""

    def __init__(self, guild: Optional[discord.Guild] = None) -> None:
        super().__init__(timeout=None)
        role_ids: dict[str, int] = {}
        if guild is not None:
            for r in guild.roles:
                role_ids[r.name] = r.id
        self.add_item(SelfAssignSelect(
            custom_id="structure:regions_select",
            placeholder="🌎 Choisis ta région d'origine",
            options_spec=REGIONS_PANEL_OPTIONS,
            role_ids=role_ids,
        ))
        self.add_item(SelfAssignSelect(
            custom_id="structure:aviation_select",
            placeholder="✈️ Quel est ton profil aviation ?",
            options_spec=AVIATION_PANEL_OPTIONS,
            role_ids=role_ids,
        ))


async def setup(bot: commands.Bot) -> None:
    cog = StructureGuard(bot)
    await bot.add_cog(cog)
    # Enregistrer les views persistantes (les custom_id matcheront aux interactions
    # même après un restart du bot).
    bot.add_view(RegionsPanelView())
    bot.add_view(AcceptRulesView())
