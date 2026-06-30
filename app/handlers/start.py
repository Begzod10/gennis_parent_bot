import logging
import requests

from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.config import TECH_API
from app.db import SessionLocal
from app.models import ParentSubscription
from app.keyboards import (
    main_keyboard,
    student_search_results_keyboard,
    subscriptions_keyboard,
    unsubscribe_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


class SearchStates(StatesGroup):
    waiting_for_name = State()


# ── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Salom! <b>Gennis Parent Bot</b>ga xush kelibsiz!\n\n"
        "Bu bot orqali farzandingizning o'qish natijalarini\n"
        "har kuni avtomatik olasiz — hech qanday parol kerak emas.\n\n"
        "👇 Boshlash uchun farzandingizni qidiring:",
        parse_mode="HTML",
        reply_markup=main_keyboard
    )


# ── Search ───────────────────────────────────────────────────────────────────

@router.message(F.text == "🔍 Farzandimni qidirish")
@router.callback_query(F.data == "add_new")
async def ask_child_name(event, state: FSMContext):
    message = event if isinstance(event, types.Message) else event.message
    if isinstance(event, types.CallbackQuery):
        await event.answer()
    await state.set_state(SearchStates.waiting_for_name)
    await message.answer(
        "👤 Farzandingizning <b>ism yoki familiyasini</b> kiriting:",
        parse_mode="HTML"
    )


@router.message(SearchStates.waiting_for_name)
async def handle_name_search(message: types.Message, state: FSMContext):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Kamida 2 ta harf kiriting.")
        return

    try:
        resp = requests.get(f"{TECH_API}/search-student", params={"q": query}, timeout=10)
        resp.raise_for_status()
        students = resp.json()
    except Exception as e:
        logger.error("Search error: %s", e)
        await message.answer("⚠️ Qidirishda xatolik yuz berdi. Keyinroq urinib ko'ring.")
        await state.clear()
        return

    if not students:
        await message.answer(
            f"😔 <b>{query}</b> bo'yicha o'quvchi topilmadi.\n"
            "Ism yoki familiyani tekshirib qayta kiriting.",
            parse_mode="HTML"
        )
        return

    await state.clear()
    await message.answer(
        f"✅ <b>{len(students)}</b> ta o'quvchi topildi.\n"
        "Farzandingizni tanlang 👇",
        parse_mode="HTML",
        reply_markup=student_search_results_keyboard(students)
    )


@router.callback_query(F.data.startswith("subscribe_"))
async def subscribe_to_student(callback: types.CallbackQuery):
    parts = callback.data.split("_", 2)
    student_id = int(parts[1])
    student_name = parts[2] if len(parts) > 2 else "O'quvchi"

    with SessionLocal() as db:
        existing = db.query(ParentSubscription).filter_by(
            telegram_id=callback.from_user.id,
            student_platform_id=student_id,
            is_active=True
        ).first()

        if existing:
            await callback.answer("✅ Siz allaqachon bu o'quvchiga obuna bo'lgansiz!", show_alert=True)
            return

        sub = ParentSubscription(
            telegram_id=callback.from_user.id,
            parent_name=callback.from_user.full_name,
            student_platform_id=student_id,
            student_name=student_name,
        )
        db.add(sub)
        db.commit()

    await callback.message.answer(
        f"🎉 <b>{student_name}</b> uchun kunlik hisobot yoqildi!\n\n"
        "📅 Har kuni soat <b>20:00</b> da o'qish natijalari yuboriladi.",
        parse_mode="HTML",
        reply_markup=main_keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Qidiruv bekor qilindi.", reply_markup=main_keyboard)
    await callback.answer()


# ── My subscriptions ─────────────────────────────────────────────────────────

@router.message(F.text == "👨‍👧 Farzandlarim ro'yxati")
async def my_subscriptions(message: types.Message):
    with SessionLocal() as db:
        subs = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id,
            is_active=True
        ).all()

    if not subs:
        await message.answer(
            "📭 Siz hali hech qanday o'quvchiga obuna bo'lmagansiz.\n"
            "🔍 Farzandingizni qidiring:",
            reply_markup=main_keyboard
        )
        return

    await message.answer(
        f"👨‍👧 Sizning farzandlaringiz ({len(subs)} ta).\n"
        "Natijalarni ko'rish uchun tanlang 👇",
        reply_markup=subscriptions_keyboard(subs)
    )


@router.callback_query(F.data.startswith("view_stats_"))
async def view_student_stats(callback: types.CallbackQuery):
    student_id = int(callback.data.split("_")[-1])
    try:
        resp = requests.get(f"{TECH_API}/student-stats/{student_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Stats fetch error: %s", e)
        await callback.answer("⚠️ Ma'lumot olishda xatolik.", show_alert=True)
        return

    await callback.message.answer(
        _format_stats(data),
        parse_mode="HTML"
    )
    await callback.answer()


# ── Unsubscribe ──────────────────────────────────────────────────────────────

@router.message(F.text == "❌ Obunani bekor qilish")
async def unsubscribe_menu(message: types.Message):
    with SessionLocal() as db:
        subs = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id,
            is_active=True
        ).all()

    if not subs:
        await message.answer("📭 Faol obunalar yo'q.", reply_markup=main_keyboard)
        return

    await message.answer(
        "🗑 Qaysi farzanddan obunani bekor qilmoqchisiz?",
        reply_markup=unsubscribe_keyboard(subs)
    )


@router.callback_query(F.data.startswith("unsub_"))
async def confirm_unsubscribe(callback: types.CallbackQuery):
    sub_id = int(callback.data.split("_")[1])
    with SessionLocal() as db:
        sub = db.query(ParentSubscription).filter_by(
            id=sub_id,
            telegram_id=callback.from_user.id
        ).first()
        if sub:
            sub.is_active = False
            db.commit()
            name = sub.student_name
        else:
            name = "O'quvchi"

    await callback.message.answer(
        f"✅ <b>{name}</b> uchun kunlik hisobot bekor qilindi.",
        parse_mode="HTML",
        reply_markup=main_keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.answer("🏠 Asosiy menyu:", reply_markup=main_keyboard)
    await callback.answer()


# ── Stats formatter ──────────────────────────────────────────────────────────

def _format_stats(data: dict) -> str:
    name = data.get("name") or "O'quvchi"
    total_pts = data.get("total_points", 0)
    rank = data.get("global_rank", 0)
    weekly = data.get("weekly_points", 0)
    courses = data.get("courses", [])

    text = (
        f"📊 <b>{name}</b> natijalari\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Umumiy ball: <b>{total_pts}</b>\n"
        f"📅 Haftalik ball: <b>{weekly}</b>\n"
        f"🥇 Reyting: <b>#{rank}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )

    for c in courses:
        done = c.get("lessons_completed", 0)
        total = c.get("lessons_total", 0)
        pct = round(done / total * 100) if total else 0
        ex = c.get("exercises", {})
        ex_correct = ex.get("correct", 0)
        ex_total = ex.get("total", 0)
        progress_bar = _progress_bar(pct)

        text += (
            f"\n📘 <b>{c['title']}</b>\n"
            f"   {progress_bar} {pct}%\n"
            f"   📖 Darslar: {done}/{total}\n"
            f"   ✏️ Mashqlar: {ex_correct}/{ex_total} to'g'ri\n"
        )

        projects = c.get("projects", [])
        status_emoji = {"Submitted": "⏳", "Approved": "✅", "Rejected": "❌", "Pending": "🔄"}
        for p in projects:
            emoji = status_emoji.get(p.get("status", ""), "📌")
            grade = f" | Baho: {p['grade']}" if p.get("grade") else ""
            text += f"   {emoji} Loyiha{grade}\n"

    return text


def _progress_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)
