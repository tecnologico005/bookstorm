#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Text Validator

Validates text before sending to speech engines or other processors.
Ensures text contains at least one alphanumeric character.
"""

import re


def is_valid_text(text):
    """
    Check if text is valid for processing

    Args:
        text: Text to validate

    Returns:
        bool: True if text contains at least one alphanumeric character, False otherwise
    """
    if not text:
        return False

    # Check if there's at least one alphanumeric character
    return bool(re.search(r'[a-zA-Z0-9]', str(text)))


def sanitize_text(text, defaultText=""):
    """
    Sanitize text for processing, returning valid text or default

    Args:
        text: Text to sanitize
        defaultText: Default text to return if invalid (default: "")

    Returns:
        str: Original text if valid, defaultText if invalid
    """
    if is_valid_text(text):
        return str(text)
    return defaultText
