from ..phone_recognizer import PhoneRecognizer as BasePhoneRecognizer


class PhoneRecognizer(BasePhoneRecognizer):
    DEFAULT_SUPPORTED_REGIONS = ("TR",)


__all__ = [
    "PhoneRecognizer",
]
