from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Farzandimni qidirish")],
        [KeyboardButton(text="👨‍👧 Farzandlarim ro'yxati")],
        [KeyboardButton(text="❌ Obunani bekor qilish")],
    ],
    resize_keyboard=True,
    input_field_placeholder="👆 Birini tanlang"
)


def student_search_results_keyboard(students: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in students:
        builder.button(
            text=f"👤 {s['name']}",
            callback_data=f"subscribe_{s['id']}_{s['name'][:30]}"
        )
    builder.button(text="❌ Bekor qilish", callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def subscriptions_keyboard(subscriptions: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subscriptions:
        builder.button(
            text=f"👤 {sub.student_name}",
            callback_data=f"view_stats_{sub.student_platform_id}"
        )
    builder.button(text="➕ Yangi qo'shish", callback_data="add_new")
    builder.adjust(1)
    return builder.as_markup()


def unsubscribe_keyboard(subscriptions: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subscriptions:
        builder.button(
            text=f"🗑 {sub.student_name}",
            callback_data=f"unsub_{sub.id}"
        )
    builder.button(text="⬅️ Ortga", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
