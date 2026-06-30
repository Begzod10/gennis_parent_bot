from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.i18n import t


def main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "btn_search"))],
            [KeyboardButton(text=t(lang, "btn_my_children"))],
            [KeyboardButton(text=t(lang, "btn_unsubscribe"))],
            [KeyboardButton(text=t(lang, "btn_language"))],
        ],
        resize_keyboard=True,
        input_field_placeholder="👆",
    )


def language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇿 O'zbek", callback_data="setlang_uz")
    builder.button(text="🇷🇺 Русский", callback_data="setlang_ru")
    builder.adjust(2)
    return builder.as_markup()


def student_search_results_keyboard(students: list, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in students:
        builder.button(
            text=f"👤 {s['name']}",
            callback_data=f"subscribe_{s['id']}_{s['name'][:30]}"
        )
    builder.button(text=t(lang, "btn_cancel"), callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def subscriptions_keyboard(subscriptions: list, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subscriptions:
        builder.button(
            text=f"👤 {sub.student_name}",
            callback_data=f"view_stats_{sub.student_platform_id}"
        )
    builder.button(text=t(lang, "btn_add_new"), callback_data="add_new")
    builder.adjust(1)
    return builder.as_markup()


def unsubscribe_keyboard(subscriptions: list, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subscriptions:
        builder.button(
            text=f"🗑 {sub.student_name}",
            callback_data=f"unsub_{sub.id}"
        )
    builder.button(text=t(lang, "btn_back"), callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
