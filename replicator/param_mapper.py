"""Fuzzy matching of API param_ids to dashboard form field labels."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FieldMapping:
    param_id: str
    field_label: str
    confidence: str  # "exact", "substring", "positional", "unmatched"


def _normalize(text: str) -> str:
    """Strip separators, lowercase: SECRET_KEY -> secretkey"""
    return re.sub(r"[_\-\s.]+", "", text).lower()


def match_params(
    param_ids: list[str],
    field_labels: list[str],
) -> list[FieldMapping]:
    """Map param_ids from the API to field labels scraped from the dashboard form.

    Matching layers:
      1. Exact normalized match
      2. Substring match (normalized param_id contained in normalized label or vice versa)
      3. Positional match (1 unmatched param, 1 unmatched field)
      4. Unmatched (returned for manual mapping in UI)
    """
    results: list[FieldMapping] = []
    unmatched_params: list[str] = []
    available_labels = list(field_labels)  # mutable copy

    for pid in param_ids:
        norm_pid = _normalize(pid)
        matched = False

        # Layer 1: exact normalized match
        for label in available_labels:
            if _normalize(label) == norm_pid:
                results.append(FieldMapping(pid, label, "exact"))
                available_labels.remove(label)
                matched = True
                break

        if matched:
            continue

        # Layer 2: substring match
        for label in available_labels:
            norm_label = _normalize(label)
            if norm_pid in norm_label or norm_label in norm_pid:
                results.append(FieldMapping(pid, label, "substring"))
                available_labels.remove(label)
                matched = True
                break

        if not matched:
            unmatched_params.append(pid)

    # Layer 3: positional match (1-to-1 remaining)
    if len(unmatched_params) == 1 and len(available_labels) == 1:
        results.append(FieldMapping(
            unmatched_params[0], available_labels[0], "positional"
        ))
        unmatched_params.clear()
        available_labels.clear()

    # Layer 4: unmatched
    for pid in unmatched_params:
        results.append(FieldMapping(pid, "", "unmatched"))

    return results
