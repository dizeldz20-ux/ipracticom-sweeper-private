"""Inline keyboards for the iPracticom Sweeper Telegram dashboard.

All keyboards are 1-column-when-long (mobile-first) or 2x2 grid
(when 4 items). The main menu is a 2x2 grid for one-thumb reach.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    """Top-level dashboard: 2x2 grid (mobile-friendly)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 מצב נוכחי", callback_data="menu:status"),
            InlineKeyboardButton("⚠️ בעיות", callback_data="menu:problems"),
        ],
        [
            InlineKeyboardButton("📈 היסטוריה", callback_data="menu:history"),
            InlineKeyboardButton("🔐 אבטחה", callback_data="menu:security"),
        ],
    ])


def status_menu() -> InlineKeyboardMarkup:
    """Status submenu: 3 metrics + back."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ CPU", callback_data="snap:cpu")],
        [InlineKeyboardButton("🧠 זיכרון", callback_data="snap:memory")],
        [InlineKeyboardButton("💾 דיסק", callback_data="snap:disk")],
        [InlineKeyboardButton("🌐 רשת", callback_data="snap:network")],
        [InlineKeyboardButton("⬅️ חזור לתפריט", callback_data="menu:main")],
    ])


def history_menu() -> InlineKeyboardMarkup:
    """History submenu: 1-col list of metrics + back."""
    metrics = [
        ("defcon", "🎯 DEFCON"),
        ("cpu_percent", "🖥️ CPU %"),
        ("memory_percent", "🧠 זיכרון %"),
        ("disk_percent", "💾 דיסק %"),
    ]
    rows = [
        [InlineKeyboardButton(label, callback_data=f"hist:{metric}")]
        for metric, label in metrics
    ]
    rows.append([InlineKeyboardButton("⬅️ חזור לתפריט", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def back_to_main() -> InlineKeyboardMarkup:
    """Single-button keyboard for inline back navigation."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזור לתפריט", callback_data="menu:main")]
    ])
