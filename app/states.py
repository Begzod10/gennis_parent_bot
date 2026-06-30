from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    awaiting_lang = State()
    awaiting_name = State()
    choosing_student = State()
    viewing_child = State()
