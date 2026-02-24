"""DynamicLookup scanner - masks internal assets (VMs, hostnames, DBs, etc.) from a dynamic store."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from presidio_anonymizer.core.text_replace_builder import TextReplaceBuilder

from ..util import calculate_risk_score, get_logger
from ..vault import Vault
from .base import Scanner

if TYPE_CHECKING:
    pass

LOGGER = get_logger()

# Risk score for matched assets
_DEFAULT_RISK_SCORE = 0.95
_THRESHOLD = 0.5


class DynamicLookup(Scanner):
    """
    Scanner that masks internal asset names (VM names, hostnames, database names, etc.)
    using a dynamically managed lookup list stored in an external asset store.

    Matched values are replaced with placeholders like [REDACTED_HOSTNAME_1] and stored
    in the Vault so they can be deanonymized later.
    """

    def __init__(
        self,
        vault: Vault,
        *,
        asset_store=None,
        fail_on_db_error: bool = True,
    ) -> None:
        """
        Initialize DynamicLookup scanner.

        Parameters:
            vault: Vault instance for storing placeholder-to-original mappings.
            asset_store: CachedAssetStore instance providing lookup data.
            fail_on_db_error: If True, block the prompt when DB/cache errors occur.
        """
        self._vault = vault
        self._asset_store = asset_store
        self._fail_on_db_error = fail_on_db_error

    def scan(self, prompt: str) -> tuple[str, bool, float]:
        if prompt.strip() == "":
            return prompt, True, -1.0

        if self._asset_store is None:
            LOGGER.warning("DynamicLookup: no asset store configured")
            if self._fail_on_db_error:
                return prompt, False, 1.0
            return prompt, True, -1.0

        try:
            assets = self._asset_store.get_lookup_data()
        except Exception:
            LOGGER.exception("DynamicLookup: failed to get lookup data")
            if self._fail_on_db_error:
                return prompt, False, 1.0
            return prompt, True, -1.0

        if not assets:
            return prompt, True, -1.0

        # Build lookup entries: (name, category) sorted longest-first
        entries: list[tuple[str, str, re.Pattern]] = []
        for asset in assets:
            names = [asset.name] + (asset.aliases or [])
            for name in names:
                if not name or len(name) < 2:
                    continue
                pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
                entries.append((name, asset.category, pattern))

        # Sort longest first to avoid partial matches
        entries.sort(key=lambda e: len(e[0]), reverse=True)

        # Find all matches with positions
        matches: list[tuple[int, int, str, str]] = []  # (start, end, category, original_value)
        for _name, category, pattern in entries:
            for m in pattern.finditer(prompt):
                matches.append((m.start(), m.end(), category, m.group()))

        if not matches:
            return prompt, True, -1.0

        # Resolve overlaps: keep longest match, then earliest position
        matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        resolved: list[tuple[int, int, str, str]] = []
        for match in matches:
            start, end, category, value = match
            overlaps = False
            for r_start, r_end, _, _ in resolved:
                if start < r_end and end > r_start:
                    overlaps = True
                    break
            if not overlaps:
                resolved.append(match)

        # Sort by position for replacement
        resolved.sort(key=lambda m: m[0])

        # Build replacements using TextReplaceBuilder
        text_replace_builder = TextReplaceBuilder(original_text=prompt)

        # Track counters per category
        category_counters: dict[str, dict[str, int]] = {}

        for _start, _end, category, value in resolved:
            if category not in category_counters:
                category_counters[category] = {}

            if value.lower() not in {v.lower() for v in category_counters[category]}:
                # Check vault for existing placeholder
                existing_placeholder = None
                prefix = f"[REDACTED_{category}_"
                for placeholder, vault_value in self._vault.get():
                    if placeholder.startswith(prefix) and vault_value.lower() == value.lower():
                        existing_placeholder = placeholder
                        break

                if existing_placeholder:
                    idx = int(existing_placeholder.split("_")[-1][:-1])
                else:
                    existing_indices = set()
                    for placeholder, _ in self._vault.get():
                        if placeholder.startswith(prefix):
                            try:
                                idx_str = placeholder.split("_")[-1][:-1]
                                existing_indices.add(int(idx_str))
                            except ValueError:
                                pass
                    for v, assigned_idx in category_counters[category].items():
                        existing_indices.add(assigned_idx)

                    idx = 1
                    while idx in existing_indices:
                        idx += 1

                category_counters[category][value] = idx
            else:
                # Find existing counter for this value (case-insensitive)
                for v, assigned_idx in category_counters[category].items():
                    if v.lower() == value.lower():
                        category_counters[category][value] = assigned_idx
                        break

        # Apply replacements in reverse order
        sorted_resolved = sorted(resolved, reverse=True, key=lambda m: m[0])
        results: list[tuple[str, str]] = []

        for start, end, category, value in sorted_resolved:
            idx = category_counters[category][value]
            placeholder = f"[REDACTED_{category}_{idx}]"
            results.append((placeholder, value))
            text_replace_builder.replace_text_get_insertion_index(placeholder, start, end)

        sanitized = text_replace_builder.output_text

        if prompt != sanitized:
            LOGGER.warning(
                "DynamicLookup: masked internal assets",
                match_count=len(resolved),
            )
            for placeholder, original_value in results:
                if not self._vault.placeholder_exists(placeholder):
                    self._vault.append((placeholder, original_value))

            return sanitized, False, calculate_risk_score(_DEFAULT_RISK_SCORE, _THRESHOLD)

        return prompt, True, -1.0
