"""Génération de rapports markdown pour dry-run et apply."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


REPORTS_DIR = Path(__file__).parent / "reports"


class Report:
    """Builder de rapport markdown.

    Utilisation :
        r = Report("dry-run")
        r.h2("Rôles")
        r.line("- créer `Directeur communauté`")
        r.alert("Le bot n'est pas placé assez haut")
        path = r.save()
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.started_at = datetime.now()
        self.lines: list[str] = []
        self.alerts: list[str] = []
        self.stats: dict[str, int] = {}
        self._write_header()

    def _write_header(self) -> None:
        ts = self.started_at.strftime("%Y-%m-%d %H:%M:%S")
        self.lines.append(f"# Rapport migration V2 — {self.kind}")
        self.lines.append("")
        self.lines.append(f"_Généré le {ts}_")
        self.lines.append("")

    def h2(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(f"## {title}")
        self.lines.append("")

    def h3(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(f"### {title}")
        self.lines.append("")

    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def bullet(self, text: str) -> None:
        self.lines.append(f"- {text}")

    def code_block(self, text: str, lang: str = "") -> None:
        self.lines.append(f"```{lang}")
        self.lines.append(text)
        self.lines.append("```")

    def alert(self, msg: str) -> None:
        self.alerts.append(msg)
        self.lines.append(f"> ⚠️ **{msg}**")

    def info(self, msg: str) -> None:
        self.lines.append(f"> ℹ️ {msg}")

    def ok(self, msg: str) -> None:
        self.lines.append(f"> ✅ {msg}")

    def stat(self, key: str, value: int) -> None:
        self.stats[key] = self.stats.get(key, 0) + value

    def summary_block(self) -> None:
        if not self.stats and not self.alerts:
            return
        self.h2("Résumé")
        if self.stats:
            for k, v in self.stats.items():
                self.bullet(f"**{k}** : {v}")
        if self.alerts:
            self.line("")
            self.line(f"**Alertes** : {len(self.alerts)}")
            for a in self.alerts:
                self.bullet(a)

    def save(self) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.summary_block()
        filename = self.started_at.strftime("%Y-%m-%d_%H%M%S") + f"_{self.kind}.md"
        path = REPORTS_DIR / filename
        path.write_text("\n".join(self.lines), encoding="utf-8")
        return path

    def __str__(self) -> str:
        return "\n".join(self.lines)
