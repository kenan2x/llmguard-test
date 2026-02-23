from typing import Callable

from presidio_analyzer import EntityRecognizer


def _get_predefined_recognizers(language: str) -> list[Callable[..., EntityRecognizer]]:
    if language == "zh":
        from .zh import CryptoRecognizer, EmailRecognizer, IpRecognizer, PhoneRecognizer

        return [
            CryptoRecognizer,
            PhoneRecognizer,
            EmailRecognizer,
            IpRecognizer,
        ]
    elif language == "tr":
        from .tr import PhoneRecognizer

        return [
            PhoneRecognizer,
        ]
    else:
        return []


__all__ = [
    "_get_predefined_recognizers",
]
