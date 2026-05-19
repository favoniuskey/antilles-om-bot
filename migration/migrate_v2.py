"""CLI principal de la migration V2.

Usage :
    python migration/migrate_v2.py --validate-target
    python migration/migrate_v2.py --dry-run
    python migration/migrate_v2.py --apply [--yes]
    python migration/migrate_v2.py --rollback <snapshot_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Forcer UTF-8 sur stdout/stderr pour les emojis et caractères accentués
# (Windows par défaut = cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# Compat exécution directe (python migration/migrate_v2.py) ET en module.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "migration"

# Imports lourds (discord, dotenv) faits en lazy dans les fonctions qui en ont
# besoin — `--validate-target` doit pouvoir tourner sans discord.py installé.

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
TARGET_FILE = Path(__file__).parent / "v2_target.json"


# ----------------------------------------------------------------------
# Snapshot
# ----------------------------------------------------------------------

def _serialize_overwrite(ow) -> dict:
    allow, deny = ow.pair()
    return {"allow": allow.value, "deny": deny.value}


def snapshot_guild(guild) -> dict:
    import discord
    """Dump l'état actuel du serveur dans un dict sérialisable."""
    data: dict = {
        "_snapshot_at": datetime.now().isoformat(),
        "guild": {"id": str(guild.id), "name": guild.name},
        "roles": [],
        "categories": [],
        "channels": [],
    }
    for r in guild.roles:
        data["roles"].append({
            "id": str(r.id),
            "name": r.name,
            "permissions": r.permissions.value,
            "color": r.color.value,
            "hoist": r.hoist,
            "mentionable": r.mentionable,
            "position": r.position,
            "managed": r.managed,
            "is_default": r.is_default(),
        })
    for c in guild.categories:
        data["categories"].append({
            "id": str(c.id),
            "name": c.name,
            "position": c.position,
            "overwrites": {
                str(target.id): _serialize_overwrite(ow)
                for target, ow in c.overwrites.items()
            },
        })
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        data["channels"].append({
            "id": str(ch.id),
            "name": ch.name,
            "type": str(ch.type),
            "category_id": str(ch.category.id) if ch.category else None,
            "position": ch.position,
            "overwrites": {
                str(target.id): _serialize_overwrite(ow)
                for target, ow in ch.overwrites.items()
            },
        })
    return data


def save_snapshot(data: dict) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = SNAPSHOTS_DIR / f"{ts}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# Discord client minimal
# ----------------------------------------------------------------------

def _build_client():
    import discord
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    return discord.Client(intents=intents)


async def _connect_and_run(handler) -> None:
    """Crée un client, se connecte, attend on_ready, exécute handler, déconnecte.

    handler(guild) est un async callable qui reçoit la guild résolue.
    """
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    guild_id = int(os.getenv("GUILD_ID", "1224706989146378371"))
    if not token:
        print("❌ DISCORD_TOKEN manquant dans .env", file=sys.stderr)
        sys.exit(2)

    client = _build_client()
    done = asyncio.Event()
    result_holder: dict = {"error": None}

    @client.event
    async def on_ready():
        try:
            guild = client.get_guild(guild_id)
            if guild is None:
                guild = await client.fetch_guild(guild_id)
            await handler(guild)
        except Exception as e:
            result_holder["error"] = e
        finally:
            done.set()
            await client.close()

    async def runner():
        await client.start(token)

    runner_task = asyncio.create_task(runner())
    await done.wait()
    try:
        await asyncio.wait_for(runner_task, timeout=10)
    except asyncio.TimeoutError:
        pass

    if result_holder["error"]:
        raise result_holder["error"]


# ----------------------------------------------------------------------
# Commandes CLI
# ----------------------------------------------------------------------

def cmd_validate_target() -> int:
    # Validation pure — n'importe pas discord (utile sans discord.py installé)
    from .validator import load_target, validate_target, stats
    try:
        target = load_target()
    except Exception as e:
        print(f"❌ Erreur de lecture {TARGET_FILE} : {e}", file=sys.stderr)
        return 2
    errors = validate_target(target)
    if errors:
        print(f"❌ {len(errors)} erreur(s) de validation :")
        for e in errors:
            print(f"  - {e}")
        return 1
    s = stats(target)
    print(f"✅ {TARGET_FILE.name} est syntaxiquement valide.")
    print(f"   - {s['roles']} rôles")
    print(f"   - {s['categories']} catégories")
    print(f"   - {s['channels']} salons")
    return 0


async def _do_dry_run(guild) -> Path:
    import discord
    from .applier import Applier
    from .differ import compute_diff, load_target
    from .reporter import Report


    report = Report("dry-run")
    report.h2("Cible")
    report.bullet(f"Serveur : `{guild.name}` (`{guild.id}`)")
    report.bullet(f"Membres : {guild.member_count}")
    report.bullet(f"Rôles actuels : {len(guild.roles)}")
    report.bullet(f"Catégories actuelles : {len(guild.categories)}")
    report.bullet(f"Salons actuels : {len([c for c in guild.channels if not isinstance(c, discord.CategoryChannel)])}")

    target = load_target()
    diff = compute_diff(guild, target)

    applier = Applier(guild, diff, report, dry_run=True)
    await applier.run_all()

    return report.save()


async def _do_apply(guild, skip_confirm: bool) -> Path:
    from .applier import Applier
    from .differ import compute_diff, load_target
    from .reporter import Report

    if not skip_confirm:
        print(f"⚠️  Vous êtes sur le point d'APPLIQUER la refonte V2 sur :")
        print(f"     {guild.name} ({guild.id})")
        print(f"     {guild.member_count} membres, {len(guild.roles)} rôles")
        print("Tapez 'OUI' pour continuer :")
        # En CLI interactive, on lit depuis stdin
        answer = (await asyncio.get_event_loop().run_in_executor(None, input, "> ")).strip()
        if answer != "OUI":
            print("❌ Annulé par l'utilisateur.")
            return Path()

    snap = snapshot_guild(guild)
    snap_path = save_snapshot(snap)
    print(f"💾 Snapshot enregistré : {snap_path}")

    report = Report("apply")
    report.h2("Snapshot")
    report.bullet(f"Snapshot pré-apply : `{snap_path.name}`")
    report.bullet(f"Pour rollback : `python migration/migrate_v2.py --rollback {snap_path.stem}`")

    target = load_target()
    diff = compute_diff(guild, target)
    applier = Applier(guild, diff, report, dry_run=False)
    success = await applier.run_all()
    report_path = report.save()
    print(f"📄 Rapport : {report_path}")
    if not success:
        print("⚠️  Migration interrompue, voir le rapport.")
    return report_path


async def _do_rollback(guild, snapshot_id: str) -> Path:
    import discord
    from .reporter import Report

    snap_path = SNAPSHOTS_DIR / f"{snapshot_id}.json"
    if not snap_path.exists():
        print(f"❌ Snapshot introuvable : {snap_path}")
        return Path()

    with snap_path.open("r", encoding="utf-8") as f:
        snap = json.load(f)

    report = Report("rollback")
    report.h2("Rollback depuis snapshot")
    report.bullet(f"Snapshot : `{snap_path.name}`")
    report.bullet(f"Pris le : `{snap.get('_snapshot_at')}`")

    snap_role_ids = {r["id"] for r in snap.get("roles", [])}
    snap_cat_ids = {c["id"] for c in snap.get("categories", [])}
    snap_ch_ids = {c["id"] for c in snap.get("channels", [])}

    # 1. Restaurer noms et perms des rôles présents au snapshot
    for r in snap.get("roles", []):
        if r.get("is_default") or r.get("managed"):
            continue
        role = guild.get_role(int(r["id"]))
        if role is None:
            report.alert(f"Rôle `{r['name']}` (id {r['id']}) du snapshot introuvable")
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
            report.alert(f"Refus restauration rôle `{r['name']}`")

    # 2. Supprimer les rôles créés depuis le snapshot
    for role in guild.roles:
        if str(role.id) in snap_role_ids or role.is_default() or role.managed:
            continue
        try:
            await role.delete(reason="Rollback V2 — rôle créé par apply")
            report.bullet(f"🗑️ Rôle `{role.name}` supprimé (créé après snapshot)")
        except discord.Forbidden:
            report.alert(f"Refus suppression rôle `{role.name}`")

    # 3. Restaurer la catégorisation des salons
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
                report.bullet(f"♻️ Salon `{ch.name}` recatégorisé")
            except discord.Forbidden:
                pass

    # 4. Supprimer salons créés depuis le snapshot
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        if str(ch.id) in snap_ch_ids:
            continue
        try:
            await ch.delete(reason="Rollback V2 — salon créé par apply")
            report.bullet(f"🗑️ Salon `{ch.name}` supprimé (créé après snapshot)")
        except discord.Forbidden:
            pass

    # 5. Supprimer catégories créées depuis le snapshot
    for cat in guild.categories:
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
    print(f"📄 Rapport rollback : {path}")
    return path


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Migration V2 du serveur Antilles-OM")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate-target", action="store_true",
                       help="Valide la syntaxe de v2_target.json sans connexion")
    group.add_argument("--dry-run", action="store_true",
                       help="Génère un rapport markdown des changements sans rien écrire")
    group.add_argument("--apply", action="store_true",
                       help="Exécute la migration (avec confirmation interactive)")
    group.add_argument("--rollback", metavar="SNAPSHOT_ID",
                       help="Restaure l'état depuis un snapshot horodaté")
    parser.add_argument("--yes", action="store_true",
                        help="Skip la confirmation pour --apply (à utiliser avec précaution)")
    args = parser.parse_args()

    if args.validate_target:
        return cmd_validate_target()

    if args.dry_run:
        async def handler(guild):
            path = await _do_dry_run(guild)
            print(f"📄 Rapport dry-run : {path}")
        asyncio.run(_connect_and_run(handler))
        return 0

    if args.apply:
        async def handler(guild):
            await _do_apply(guild, skip_confirm=args.yes)
        asyncio.run(_connect_and_run(handler))
        return 0

    if args.rollback:
        async def handler(guild):
            await _do_rollback(guild, args.rollback)
        asyncio.run(_connect_and_run(handler))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
