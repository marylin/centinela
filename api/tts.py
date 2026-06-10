"""Spoken alerts: Cloud Text-to-Speech of the translated resident alert.

Honesty rule for voices: if TTS does not support the resident language, we
speak the ENGLISH text with an English voice rather than feeding text to a
mismatched voice. Small in-process LRU; regeneration is near-free.
"""
from collections import OrderedDict

from api.core import TESTING

# Resident language -> TTS voice language code. Missing = speak English.
TTS_LANG = {
    "en": "en-US", "es": "es-US", "pt": "pt-BR", "id": "id-ID",
    "fil": "fil-PH", "bn": "bn-IN", "tr": "tr-TR", "ja": "ja-JP",
    "zh-TW": "cmn-TW", "th": "th-TH", "vi": "vi-VN", "el": "el-GR",
    "it": "it-IT",
}

_CACHE = OrderedDict()  # key -> mp3 bytes
_CACHE_MAX = 32
_CLIENT = None

# A tiny silent-ish MP3 stub for TESTING (valid enough for content-type tests).
_TESTING_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 16


def synthesize_alert(text_localized, text_english, lang):
    """MP3 bytes for the alert. Returns (audio_bytes, spoken_lang)."""
    voice_lang = TTS_LANG.get(lang)
    if voice_lang:
        text, spoken = text_localized, lang
    else:
        text, spoken = text_english, "en"
        voice_lang = "en-US"

    if TESTING:
        return _TESTING_MP3, spoken

    key = f"{voice_lang}:{hash(text)}"
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key], spoken

    global _CLIENT
    from google.cloud import texttospeech
    if _CLIENT is None:
        _CLIENT = texttospeech.TextToSpeechClient()
    resp = _CLIENT.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text[:4500]),
        voice=texttospeech.VoiceSelectionParams(language_code=voice_lang),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
    )
    _CACHE[key] = resp.audio_content
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return resp.audio_content, spoken
