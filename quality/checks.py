"""Funções de validação de formato e dígito verificador, usadas pelas regras das classes.

Todas recebem um texto e devolvem True/False. Não levantam erro para entrada ruim.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime


def _only(text: str, allowed: str) -> str:
    return "".join(ch for ch in str(text) if ch in allowed)


def iso7064_mod11_2(text: str) -> bool:
    """ORCID e ISNI: 16 caracteres, o último pode ser X (valor 10)."""
    digits = re.sub(r"[\s-]", "", str(text)).upper()
    if not re.fullmatch(r"[0-9]{15}[0-9X]", digits):
        return False
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def cnpj(text: str) -> bool:
    d = re.sub(r"\D", "", str(text))
    if len(d) != 14 or len(set(d)) == 1:
        return False

    def digit(base: str, weights: list[int]) -> str:
        r = sum(int(a) * b for a, b in zip(base, weights)) % 11
        return "0" if r < 2 else str(11 - r)

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = digit(d[:12], w1)
    d2 = digit(d[:12] + d1, [6] + w1)
    return d[12:] == d1 + d2


def cpf(text: str) -> bool:
    d = re.sub(r"\D", "", str(text))
    if len(d) != 11 or len(set(d)) == 1:
        return False

    def digit(base: str) -> str:
        r = sum(int(ch) * w for ch, w in zip(base, range(len(base) + 1, 1, -1))) * 10 % 11
        return "0" if r == 10 else str(r)

    d1 = digit(d[:9])
    return d[9:] == d1 + digit(d[:9] + d1)


def issn(text: str) -> bool:
    """ISSN XXXX-XXXX com dígito verificador (módulo 11; o último pode ser X)."""
    t = str(text).strip().upper()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{3}[0-9X]", t):
        return False
    d = t.replace("-", "")
    total = sum(int(ch) * w for ch, w in zip(d[:7], range(8, 1, -1)))
    check = (11 - total % 11) % 11
    return d[7] == ("X" if check == 10 else str(check))


def isbn(text: str) -> bool:
    """ISBN-10 ou ISBN-13 com dígito verificador; hifens e espaços são ignorados."""
    d = re.sub(r"[\s-]", "", str(text)).upper()
    if re.fullmatch(r"[0-9]{13}", d):
        total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(d[:12]))
        return d[12] == str((10 - total % 10) % 10)
    if re.fullmatch(r"[0-9]{9}[0-9X]", d):
        total = sum((10 - i) * int(ch) for i, ch in enumerate(d[:9]))
        check = (11 - total % 11) % 11
        return d[9] == ("X" if check == 10 else str(check))
    return False


def md5_hex(text: str) -> str:
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()


def parse_date(text: str):
    """Aceita dd/mm/aaaa, aaaa-mm-dd (com ou sem hora) e aaaa. Devolve date ou None."""
    t = str(text).strip()
    if re.fullmatch(r"[0-9]{4}", t):
        return date(int(t), 1, 1)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            continue
    return None
