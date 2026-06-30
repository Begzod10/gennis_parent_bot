from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from app.i18n import t


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text="🇺🇿 O'zbek"),
            KeyboardButton(text="🇷🇺 Русский"),
        ]],
        resize_keyboard=True,
    )


def main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "btn_search")), KeyboardButton(text=t(lang, "btn_my_children"))],
            [KeyboardButton(text=t(lang, "btn_language")), KeyboardButton(text=t(lang, "btn_unsubscribe"))],
        ],
        resize_keyboard=True,
    )


def results_keyboard(names: list, lang: str) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=name)] for name in names]
    rows.append([KeyboardButton(text=t(lang, "btn_back"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def child_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "btn_unsubscribe"))],
            [KeyboardButton(text=t(lang, "btn_back"))],
        ],
        resize_keyboard=True,
    )
