"""Все пользовательские тексты — одним местом. Parse mode: HTML.

Приём и ответы живут в общей беседе, поэтому тексты короткие и с упоминанием
адресата: в общем чате должно быть сразу понятно, кому именно бот отвечает.
"""

from __future__ import annotations

from html import escape

from bot.db.enums import RejectReason
from bot.services.anti_cheat import FlagCode, RejectCode
from bot.utils.timeutil import circles_word, days_word, plural_ru


def esc(value: object) -> str:
    return escape(str(value), quote=False)


# ── правила и старт ──────────────────────────────────────────────


HEALTH_DISCLAIMER = (
    "⚠️ <b>Про здоровье.</b> Участие добровольное и на свой страх и риск. "
    "Организаторы челленджа и бот <b>не несут ответственности</b> за твоё "
    "самочувствие, травмы и последствия нагрузки. Оценивай себя сам: "
    "при боли, головокружении или недомогании — прекрати и не сдавай день. "
    "Есть хронические болезни, проблемы со спиной, давлением или сердцем, "
    "недавняя травма или беременность — сначала посоветуйся с врачом. "
    "Серия не стоит здоровья."
)


# Стартовый текст призов GOATS: миграция 0013 переносит его в клуб, дальше
# он живёт там и правится командой /setclub prizes.
PRIZES = (
    "🎁 <b>Призы призёрам месяца</b>\n\n"
    "☕️ <b>Алия</b> — кофе\n"
    "🍗 <b>Азамат</b> — Popeyes\n"
    "🍔 <b>Амир</b> — бургер с Сатпаева\n\n"
    "<b>Плюс призовой фонд клуба:</b>\n"
    "👕 мерч\n"
    "💸 деньги\n"
    "🎽 слоты на забеги\n"
    "🍯 спортпит — гели, изотоники\n\n"
    "Достаются тем, кто займёт призовые места по итогам месяца. "
    "Фонд пополняется — хочешь добавить своё, напиши админу."
)


def _deadline_rule(boundary_hour: int) -> str:
    """При нулевой границе день = календарные сутки, и объяснять сдвиг нечего."""
    if boundary_hour == 0:
        return (
            "День заканчивается в <b>00:00</b>. Что не сдал до полуночи — "
            "то пропустил, ночной форы нет."
        )
    return (
        f"День заканчивается в <b>{boundary_hour:02d}:00</b>. Кружок, отправленный "
        f"ночью до {boundary_hour:02d}:00, идёт за прошедший день."
    )


def rules_text(
    task: str,
    min_sec: int,
    max_sec: int,
    boundary_hour: int = 0,
    daily_code: bool = True,
    prizes: str = "",
) -> str:
    """Пункты собираются списком, а не хардкодом: слово дня отключаемое,
    и при DAILY_CODE_ENABLED=false правила не должны про него врать."""
    points = [f"Каждый день — один видеокружок в этой беседе: <b>{esc(task)}</b>."]
    points.append(
        f"Длительность — не меньше минуты (от {min_sec} секунд). "
        "Стойку держим всю минуту, от начала до конца кружка."
    )
    if daily_code:
        points.append(
            "В начале кружка назови <b>слово дня</b> — бот присылает его сюда в 09:00. "
            "Заранее записать кружок не выйдет: слова ещё нет."
        )
    points += [
        "Телефон подпираем так, чтобы в кадр попало всё тело сбоку: видно и корпус, и опору.",
        _deadline_rule(boundary_hour),
        "Кружок засчитывается <b>сразу</b>. Судья потом смотрит и может отменить "
        "зачёт — тогда переснимай и присылай снова, пока идёт день.",
        "Пропустил день — серия обнуляется. Заморозок нет.",
        "Один кружок в день — <b>минимум</b>. Сверх него можно сдавать сколько угодно: "
        "<b>победитель месяца — у кого больше всего зачтённых кружков</b>. "
        "Серию удлиняет только сам факт дня, а не количество.",
        "Пересланные и повторные кружки не принимаются.",
    ]
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(points, start=1))
    # Призы свои у каждого клуба, и у нового их обычно нет — тогда блока
    # в правилах просто не будет, а не чужие обещания.
    blocks = [f"<b>Правила</b>\n\n{numbered}"]
    if prizes:
        blocks.append(prizes)
    blocks.append(HEALTH_DISCLAIMER)
    return "\n\n".join(blocks)


def launch_notice(start_date_str: str) -> str:
    return (
        f"🚀 <b>Официально стартуем {esc(start_date_str)}.</b>\n"
        "Сейчас всё в тестовом режиме: можно пробовать, ничего не сломаешь. "
        "Сдачи и серии до старта в зачёт не идут."
    )


def start_greeting(title: str, rules: str, start_date_str: str, is_test: bool) -> str:
    head = f"<b>{esc(title)}</b>\n\n"
    if is_test:
        head += launch_notice(start_date_str) + "\n\n"
    return head + rules + "\n\nЖми кнопку — и присылай кружок сюда же."


def already_joined(day: int) -> str:
    return f"Ты уже в челлендже. Сегодня день {day}."


def joined_popup(day: int, code: str | None) -> str:
    text = f"Ты в челлендже. Сегодня день {day}.\n\n"
    if code:
        text += f"Слово дня: {code}\nСкажи его в начале кружка."
    else:
        text += "Присылай кружок в беседу."
    return text


def welcome(names: str, rules: str) -> str:
    return f"👋 {names}, тут челлендж.\n\n{rules}"


def joined_chat(mention: str, day: int) -> str:
    return f"🐐 {mention} в челлендже. Сегодня день {day}."


def help_text(task: str, is_judge: bool, is_admin: bool, daily_code: bool = True) -> str:
    """Список команд по роли: обычному участнику незачем видеть /wipe_test."""
    blocks = [
        f"<b>Что делаем:</b> {esc(task)}.\n"
        "Кружок просто присылай в эту беседу — команда не нужна.\n",
        "<b>Команды</b>\n"
        "/stats — моя статистика\n"
        "/top — топ месяца по кружкам\n"
        "/alltime — топ за всё время\n"
        + ("/code — слово дня\n" if daily_code else "")
        + "/rules — правила\n"
        "/prizes — призы призёрам месяца\n"
        "/judges — кто судит\n"
        "/leave — выйти из челленджа",
        "<b>🏃 Тренировки</b>\n"
        "/next — ближайшая\n"
        "/schedule — расписание на 7 дней\n"
        "/past — прошедшие\n"
        "/attendance — рейтинг приходов за месяц\n"
        "/mytrainings — моя статистика по тренировкам\n\n"
        "<i>Пришёл на тренировку — скинь скриншот Стравы в топик «Приходы». "
        "Бот сам поймёт, к какой тренировке, и засчитает сразу.</i>",
    ]
    if is_judge:
        blocks.append(
            "<b>Судье</b>\n"
            "<i>Кружки и приходы засчитываются сами. Твоё дело — отменить, "
            "если что-то не так; сроков на это нет.</i>\n"
            "/queue — кружки за сегодня\n"
            "/pending — сколько сдано сегодня\n"
            "/checkins — приходы за сегодня\n"
            "/undo &lt;id&gt; — снять свою отмену"
        )
    if is_admin:
        blocks.append(
            "<b>Админу</b>\n"
            "/trainings — создать и вести тренировки\n"
            "/dashboard /export /backup /chatid\n"
            "/set_code /broadcast /ban /unban\n"
            "/simulate_day /wipe_test — только в тестовом режиме"
        )
    return "\n\n".join(blocks)


CHALLENGE_NOT_STARTED = "Челлендж ещё не начался. Старт — {date}."
NOT_REGISTERED = "Ты ещё не в челлендже. Нажми /start и присоединяйся."

LEAVE_CONFIRM = (
    "Точно уходишь? Серия обнулится, статистика останется.\n"
    "Вернуться можно через /start, но пропущенные дни не восстановятся."
)
LEAVE_DONE = "Ты вышел из челленджа. Будет настроение — возвращайся через /start."
LEAVE_CANCELLED = "Отменил, остаёшься."

BLOCKED = "Доступ к боту закрыт. Если это ошибка — напиши администратору."
WRONG_CHAT = "Кружки принимаются только в общей беседе челленджа."


# ── приём кружка ─────────────────────────────────────────────────


def accepted(
    mention: str,
    day: int,
    attempt: int,
    *,
    praise: str,
    circles_month: int,
    month: str,
    streak: int,
    quote: str,
    milestone: str | None = None,
) -> str:
    """Ответ на зачтённый кружок: похвала, счёт и высказывание."""
    head = f"🐐 {mention}, {esc(praise)}!"
    if attempt > 1:
        head += f" Кружок №{attempt} за сегодня."

    lines = [
        head,
        f"📅 День {day} · за {esc(month)}: <b>{circles_month}</b> "
        f"{circles_word(circles_month)} · серия {streak} {days_word(streak)} 🔥",
    ]
    if milestone:
        lines.append(esc(milestone))
    lines += ["", f"<i>{esc(quote)}</i>"]
    return "\n".join(lines)


NOT_A_VIDEO_NOTE = (
    "Нужен именно <b>кружок</b>, а не обычное видео: зажми иконку микрофона "
    "справа от поля ввода и нажми на неё один раз — она переключится на камеру. "
    "Длительность — полная минута."
)

COOLDOWN = "Не так быстро — подожди {seconds} сек."

_REJECTIONS: dict[RejectCode, str] = {
    RejectCode.FORWARDED: "{mention}, пересланные кружки не принимаются. Запиши свой.",
    RejectCode.BAD_DURATION: (
        "{mention}, кружок должен быть на полную минуту, у тебя {duration}. "
        "Держи кнопку записи до конца."
    ),
    RejectCode.DUPLICATE: "{mention}, этот кружок уже отправляли. Нужен новый.",
    RejectCode.NOT_REGISTERED: "{mention}, ты ещё не в челлендже. Нажми /start.",
    RejectCode.LEFT_CHALLENGE: "{mention}, ты вышел из челленджа. Вернуться — /start.",
    RejectCode.BLOCKED: "{mention}, доступ закрыт.",
    RejectCode.CHALLENGE_INACTIVE: "Челлендж сейчас неактивен.",
    RejectCode.NOT_STARTED: "Челлендж ещё не начался. Старт — {start_date}.",
    RejectCode.FINISHED: "Челлендж завершён. Спасибо за участие!",
    RejectCode.NOT_VIDEO_NOTE: NOT_A_VIDEO_NOTE,
}


def rejection(
    code: RejectCode, *, mention: str = "", duration: int = 0, start_date: str = ""
) -> str:
    template = _REJECTIONS.get(code, "❌ Кружок не принят.")
    return template.format(
        mention=mention, duration=f"{duration} сек", start_date=start_date
    )


# ── вердикты (реплаем на кружок в беседе) ────────────────────────


def verdict_approved(mention: str, day: int, streak: int, judge: str) -> str:
    return (
        f"🐐 {mention}, день {day} зачтён.\n"
        f"Серия: <b>{streak} {days_word(streak)}</b> 🔥\n"
        f"<i>Судья: {esc(judge)}</i>"
    )


def verdict_rejected(
    mention: str, day: int, reason: str, deadline: str, day_over: bool, judge: str
) -> str:
    text = f"❌ {mention}, зачёт за день {day} отменён: {esc(reason)}."
    text += (
        # Поздняя отмена не рвёт серию: день закрыт, минус только в счёте.
        "\nДень уже закрыт — серия цела, но этот кружок ушёл из зачёта месяца."
        if day_over
        else f"\nМожешь переснять — приём до {deadline}."
    )
    return text + f"\n<i>Судья: {esc(judge)}</i>"


def verdict_undone(mention: str, day: int) -> str:
    return f"↩️ {mention}, отмена по дню {day} отыграна назад — кружок снова зачтён."


REJECT_REASON_TEXTS: dict[RejectReason, str] = {
    RejectReason.NO_CODE_WORD: "не сказал слово дня",
    RejectReason.OFF_TOPIC: "не по заданию",
    RejectReason.TOO_SHORT: "слишком короткий кружок",
    RejectReason.REPEAT: "повтор",
    RejectReason.EDITED: "подозрение на монтаж",
    RejectReason.CUSTOM: "своя причина",
}


# ── слово дня ────────────────────────────────────────────────────


def morning_post(day: int, task: str, code: str | None, deadline: str, month: str) -> str:
    """Утренний пост: с чего начинается день челленджа."""
    lines = [
        f"☀️ <b>День {day}</b>",
        "",
        f"Задание: <b>{esc(task)}</b>",
    ]
    if code:
        lines.append(f"Слово дня: <b>{esc(code)}</b> — скажи его в начале кружка")
    lines += [
        "",
        f"Минимум один кружок до {deadline}. Сверх минимума — сколько хочешь: "
        f"кто наберёт больше всех за {esc(month)}, тот и победил.",
    ]
    return "\n".join(lines)


def daily_code_current(code: str, day: int) -> str:
    return f"🔤 День {day}. Слово дня — <b>{esc(code)}</b>."


CODE_DISABLED = "Слово дня выключено."
CODE_NOT_SET = "Слово дня ещё не назначено. Оно приходит в 09:00."


# ── напоминания и итоги дня ──────────────────────────────────────


def reminder(day: int, deadline: str, mentions: list[str]) -> str:
    who = ", ".join(mentions)
    return (
        f"⏰ День {day} ещё не сдан: {who}.\n"
        f"Приём кружков — до {deadline}."
    )


def daily_digest(
    *,
    day: int,
    date_str: str,
    done: list[str],
    missed: list[str],
    broken: list[str],
    top_name: str | None,
    top_streak: int,
    month: str = "",
    month_top: list[str] | None = None,
    day_top: list[str] | None = None,
) -> str:
    """Дневной топ — главный блок, месячный идёт хвостом.

    Месячный к середине месяца замирает: те же три имени каждую ночь.
    Дневной меняется, поэтому он выше и подробнее, а месячный оставлен
    коротким — за призы соревнуются именно в нём, прятать его нельзя.
    """
    lines = [f"<b>Итоги дня {day}</b> ({date_str})", ""]
    lines.append(f"✅ Сдали ({len(done)}): " + (", ".join(done) if done else "—"))
    lines.append(f"❌ Пропустили ({len(missed)}): " + (", ".join(missed) if missed else "—"))
    if broken:
        lines.append("")
        lines.append(f"💔 Серия прервалась: {', '.join(broken)}")
    if day_top:
        lines.append("")
        lines.append("<b>🔥 Больше всех за день</b>")
        lines.extend(day_top)
    if top_name and top_streak:
        lines.append("")
        lines.append(
            f"🐐 Самая длинная серия: <b>{esc(top_name)}</b> — "
            f"{top_streak} {days_word(top_streak)}"
        )
    if month_top:
        lines.append("")
        lines.append(f"<b>🏆 Зачёт за {esc(month)}</b>")
        lines.extend(month_top)
    return "\n".join(lines)


# ── карточка судьи ───────────────────────────────────────────────

_FLAG_TEXTS: dict[FlagCode, str] = {
    FlagCode.LAST_MINUTES: "сдача в последние минуты дня",
    FlagCode.VIA_BOT: "отправлено через стороннего бота",
    FlagCode.MANY_ATTEMPTS: "третья и далее попытка за день",
    FlagCode.FAST_RETRY: "между попытками меньше минуты",
}


def flag_text(flag: str) -> str:
    try:
        return _FLAG_TEXTS[FlagCode(flag)]
    except ValueError:
        return flag


def judge_card(
    *,
    submission_id: int,
    telegram_id: int,
    day: int,
    name: str,
    username: str | None,
    duration: int,
    attempt: int,
    code_word: str | None,
    task: str,
    streak: int,
    approved: int,
    total: int,
    percent: int,
    flags: list[str],
) -> str:
    """Оба id — в <code>: в Telegram такой текст копируется одним тапом.

    Номер сдачи нужен для /undo, id участника — для /ban и чтобы отличить
    тёзок: ник есть не у всех, а имя человек может поменять когда угодно.
    """
    handle = f" (@{esc(username)})" if username else ""
    lines = [
        f"<b>Сдача #{submission_id}</b> · День {day}",
        f"{esc(name)}{handle} · id <code>{telegram_id}</code>",
        f"Длительность: {duration} сек · Кружок №{attempt} за день",
        f"Задание: {esc(task)}",
    ]
    if code_word:
        lines.append(f"Слово дня: <b>{esc(code_word)}</b>")
    lines.append(f"Серия: {streak} {days_word(streak)} · Выполнено: {approved}/{total} ({percent}%)")
    if flags:
        lines.append("⚠️ Флаги: " + ", ".join(flag_text(f) for f in flags))
    lines.append(f"<i>Передумал после вердикта:</i> <code>/undo {submission_id}</code>")
    return "\n".join(lines)


def judge_card_resolved(card: str, approved: bool, judge: str, at: str) -> str:
    mark = "✅ Подтвердил" if approved else "❌ Отменил зачёт"
    return f"{card}\n\n<b>{mark} {esc(judge)} в {at}</b>"


def judge_card_rejected_with_reason(card: str, judge: str, at: str, reason: str) -> str:
    return f"{card}\n\n<b>❌ Отменил зачёт {esc(judge)} в {at}</b>\nПричина: {esc(reason)}"


JUDGES_HEADER = "<b>👨‍⚖️ Судьи ({count})</b>\n\n"
JUDGES_EMPTY = "Судьи ещё не назначены — список задаётся в JUDGE_IDS."
JUDGES_FOOTER = (
    "\n\n<i>Список задаётся в конфиге. Судить может только тот, кто в нём есть, "
    "даже если он состоит в группе модерации.</i>"
)


def judges_line(
    name: str, username: str | None, is_admin: bool, known: bool, verdicts: int = 0
) -> str:
    handle = f" (@{esc(username)})" if username else ""
    mark = " · админ" if is_admin else ""
    if not known:
        # Человека вписали в JUDGE_IDS, но боту он ещё не писал.
        return f"• <code>{esc(name)}</code>{mark} — ещё не запускал бота"
    return f"• {esc(name)}{handle}{mark} — {verdicts} за месяц"


ALREADY_JUDGED = "Уже посмотрел: {judge}"
NOT_A_JUDGE = "Ты не в списке судей."
SELF_JUDGE = "Свою сдачу судить нельзя."
SUBMISSION_GONE = "Сдача не найдена — возможно, её удалили."
ASK_CUSTOM_REASON = "Напиши причину незачёта одним сообщением (или /cancel)."
CUSTOM_REASON_SAVED = "Причина сохранена."

QUEUE_EMPTY = "🎉 Всё просмотрено."


def queue_header(total: int, shown: int) -> str:
    """«Ещё не смотрели», а не «висит в очереди»: кружки уже зачтены, никто
    никого не ждёт. Это список для выборочной проверки, а не долг судьи."""
    tail = f", показаны первые {shown}" if shown < total else ""
    return f"Ещё не смотрели — <b>{total}</b>{tail}. Все кружки уже зачтены:"


PENDING_COUNT = "Ещё не смотрели: <b>{count}</b>. Кружки уже зачтены."


UNDO_OK = "↩️ Отмена зачёта по сдаче #{id} снята, кружок снова в зачёте."
UNDO_NOT_YOURS = "Это не твой вердикт. Отменить может его автор или админ."
UNDO_NOT_JUDGED = "По этой сдаче ещё нет вердикта."
UNDO_USAGE = "Использование: /undo &lt;submission_id&gt;"


# ── статистика ───────────────────────────────────────────────────


def stats(
    *,
    mention: str,
    day: int,
    month: str,
    current_streak: int,
    best_streak: int,
    circles_month: int,
    circles_total: int,
    approved: int,
    rejected: int,
    missed: int,
    total: int,
    percent: int,
    calendar: str,
) -> str:
    return (
        f"<b>{mention}</b> · день {day}\n\n"
        f"🥇 Кружков за {esc(month)}: <b>{circles_month}</b>\n"
        f"📦 Всего за челлендж: {circles_total}\n\n"
        f"🔥 Текущая серия: <b>{current_streak} {days_word(current_streak)}</b>\n"
        f"🏆 Лучшая серия: {best_streak} {days_word(best_streak)}\n\n"
        f"✅ Дней закрыто: {approved}/{total} ({percent}%)\n"
        f"❌ Отклонено кружков: {rejected}\n"
        f"⬛ Пропущено дней: {missed}\n\n"
        f"{calendar}"
    )


def top_header(month: str | None) -> str:
    if month is None:
        return "<b>🏆 Топ за всё время</b>\n<i>по числу зачтённых кружков</i>\n\n"
    return (
        f"<b>🏆 Топ за {esc(month)}</b>\n"
        "<i>по числу зачтённых кружков; 1-го числа счёт обнуляется</i>\n\n"
    )


TOP_EMPTY = "Пока никто не сдал ни одного кружка."


def top_line(place: int, name: str, approved: int, streak: int, is_me: bool = False) -> str:
    medal = {1: "🐐", 2: "🥈", 3: "🥉"}.get(place, f"{place}.")
    line = f"{medal} {esc(name)} — {approved} {circles_word(approved)} · серия {streak}"
    return f"<b>{line}</b>" if is_me else line


def day_top_line(place: int, name: str, circles: int) -> str:
    """Без серии: серия — про месяц, а здесь речь ровно про сегодня."""
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, f"{place}.")
    return f"{medal} {esc(name)} — {circles} {circles_word(circles)}"


def weekly_digest(lines: list[str], circles: int, top_streak_name: str | None,
                  top_streak: int) -> str:
    body = "\n".join(lines) if lines else "—"
    text = (
        "<b>📅 Итоги недели</b>\n"
        f"<i>всего зачтено кружков: {circles}</i>\n\n"
        f"{body}"
    )
    if top_streak_name and top_streak:
        text += (
            f"\n\n🐐 Самая длинная серия: <b>{esc(top_streak_name)}</b> — "
            f"{top_streak} {days_word(top_streak)}"
        )
    return text


def record_hint(current: int, best: int) -> str:
    """Личный рекорд как цель: до него всегда понятная дистанция."""
    if best <= 0:
        return ""
    if current >= best:
        return "\n\n🏅 Это твой личный рекорд — держи."
    return f"\n\n🏅 До личного рекорда ({best}) — {best - current} {days_word(best - current)}."


def top_my_place(place: int, total: int) -> str:
    return f"\n\nТы на <b>{place}</b> месте из {total}."


# ── админ ────────────────────────────────────────────────────────

NOT_ADMIN = "Команда только для администраторов."


def chat_migrated(var_name: str, old_id: int, new_id: int) -> str:
    return (
        "⚠️ <b>Чат сменил id.</b> Группу апгрейднули до супергруппы.\n\n"
        f"Было: <code>{old_id}</code>\n"
        f"Стало: <code>{new_id}</code>\n\n"
        f"Обнови <b>{var_name}</b> в .env и перезапусти бота — иначе он "
        "перестанет принимать кружки. Старые сдачи не потеряются."
    )


def dashboard(
    *,
    challenge_title: str,
    is_test: bool,
    day: int,
    active: int,
    submitted_today: int,
    approved_today: int,
    avg_percent: int,
    dropoff: str,
) -> str:
    mode = "🧪 тестовый" if is_test else "🚀 боевой"
    return (
        f"<b>{esc(challenge_title)}</b> ({mode})\n"
        f"День {day}\n\n"
        f"👥 Активных участников: {active}\n"
        f"📨 Сдач сегодня: {submitted_today} (зачтено {approved_today})\n"
        f"📊 Средний процент: {avg_percent}%\n\n"
        f"<b>Отвал по дням</b>\n{dropoff or '—'}"
    )


SET_CODE_USAGE = "Использование: /set_code &lt;YYYY-MM-DD&gt; &lt;слово&gt;"
SET_CODE_OK = "Слово на {date} — <b>{code}</b>."
SIMULATE_USAGE = "Использование: /simulate_day &lt;YYYY-MM-DD&gt;"
SIMULATE_ONLY_TEST = "Симуляция доступна только в тестовом режиме."
SIMULATE_OK = "День {date} (№{day}) закрыт вручную. Пропусков: {missed}."
WIPE_CONFIRM = (
    "⚠️ Это сотрёт <b>все</b> тестовые сдачи и участия. "
    "Боевые данные не пострадают.\n\nПодтверждаешь?"
)
WIPE_DONE = "Тестовые данные удалены: сдач {submissions}, участий {participations}."
WIPE_CANCELLED = "Отменено."
WIPE_ONLY_TEST = "Доступно только при TEST_MODE=true."
BAN_USAGE = "Использование: /ban &lt;telegram_id&gt; [причина]"
UNBAN_USAGE = "Использование: /unban &lt;telegram_id&gt;"
BAN_OK = "Пользователь {id} заблокирован."
UNBAN_OK = "Пользователь {id} разблокирован."
USER_NOT_FOUND = "Пользователь не найден."
BROADCAST_USAGE = "Использование: /broadcast &lt;текст&gt;"
BROADCAST_DONE = "Отправлено в беседу."
EXPORT_EMPTY = "Пока нечего выгружать."
EXPORT_CAPTION = "Выгрузка на {date}"
BACKUP_CAPTION = "Бэкап БД {date}"
BACKUP_TOO_BIG = "Бэкап {name} готов ({size} МБ), но слишком большой для отправки. Лежит в {path}."

GENERIC_ERROR = "Что-то пошло не так. Попробуй ещё раз через минуту."
CANCELLED = "Отменено."


# ═════════════════════════════════════════════════════════════════
#  Тренировки бегового клуба
# ═════════════════════════════════════════════════════════════════

RSVP_LABELS = {"going": "💪 Буду", "maybe": "🤔 Возможно", "not_going": "❌ Не буду"}

# Порядок вариантов опроса = порядок статусов. Ответ Telegram отдаёт индексом,
# поэтому переставлять нельзя: сломается разбор уже отправленных опросов.
POLL_ORDER = ("going", "maybe", "not_going")
POLL_OPTIONS = [RSVP_LABELS[k] for k in POLL_ORDER]


def poll_question(day: str, clock: str) -> str:
    return f"Тренировка {day} в {clock} — идёшь?"


def _bullets(block: str) -> str:
    """Пункты хранятся построчно, буллеты рисует шаблон — так админу
    не нужно ставить их вручную, а формат остаётся единым."""
    items = [line.strip(" •-–—\t") for line in block.splitlines() if line.strip(" •-–—\t")]
    return "\n".join(f"• {esc(i)}" for i in items)


def training_post(
    *,
    weekday: str,
    day: str,
    clock: str,
    training_type: str = "",
    weather: str = "",
    plan: str = "",
    gear: str = "",
    location: str = "",
    location_url: str = "",
    notes: str = "",
    description: str = "",
    cancelled: bool = False,
) -> str:
    """Пост тренировки в чат клуба — в том виде, в каком клуб их и пишет."""
    lines = []
    if cancelled:
        lines.append("🚫 <b>ОТМЕНЕНА</b>\n")
    lines.append(f"🏃‍♂️ <b>Тренировка {esc(weekday)}, {esc(day)}, в {esc(clock)}</b>")

    # У клуба тип зашит в план, поэтому отдельной строкой он не нужен.
    # Но у быстрой тренировки «завтра, парк, забег» плана нет — и без типа
    # пост не сказал бы, что вообще происходит.
    if training_type and not plan:
        lines += ["", f"🔥 <b>{esc(training_type)}</b>"]
    if weather:
        lines += ["", f"🌦️ Погода: {esc(weather)}"]
    if plan:
        lines += ["", "<b>План тренировки:</b>", _bullets(plan)]
    if description:
        lines += ["", esc(description)]
    if gear:
        lines += ["", "<b>Рекомендуем взять:</b>", _bullets(gear)]

    lines += ["", "Сбор чуть заранее."]

    if location:
        place = f"📍 Локация: {esc(location)}"
        lines += ["", place]
        if location_url:
            lines.append(esc(location_url))

    if notes:
        for note in [n.strip() for n in notes.splitlines() if n.strip()]:
            lines += ["", esc(note)]

    return "\n".join(lines)


TRAINING_PREVIEW_HINT = "\n\n<i>Так это увидят в чате. Публикуем?</i>"
TRAINING_NO_CHAT = (
    "⚠️ Чат клуба не задан — публиковать некуда.\n"
    "Добавь бота в чат, выполни там /chatid и пропиши TRAININGS_CHAT_ID."
)
TRAINING_PUBLISHED = "✅ Опубликовано в чате клуба."
TRAINING_UPDATED = "✅ Обновлено — пост в чате перезаписан."
TRAINING_SAVED_DRAFT = "📝 Сохранено в черновики."
TRAINING_CANCELLED = "🚫 Тренировка отменена."
TRAINING_DELETED = "🗑 Тренировка удалена."
TRAINING_REPUBLISHED = (
    "🔄 Опубликовано заново. Старый пост убран, опрос начался с нуля — "
    "но кто отмечался, бот помнит: напоминания придут им же."
)
TRAINING_REPUBLISHED_STALE = (
    "🔄 Опубликовано заново, но старый пост удалить не вышло — он старше "
    "48 часов, Telegram такие не отдаёт. Убери его вручную, иначе в ветке "
    "будет два сбора."
)


def training_purge_confirm(day: str, clock: str, checkins: int) -> str:
    """Про приходы предупреждаем отдельно: их потеря — не то, чего ждут,
    нажимая «удалить пост»."""
    lines = [
        f"🗑 <b>Удалить тренировку {esc(day)}, {esc(clock)}?</b>",
        "",
        "Из чата пропадут пост, опрос и присланные под ними скриншоты.",
    ]
    if checkins:
        lines.append(
            f"⚠️ Вместе с ней удалятся <b>{checkins}</b> "
            f"{plural_ru(checkins, 'приход', 'прихода', 'приходов')} — "
            "они исчезнут из рейтинга."
        )
    lines.append("")
    lines.append("Отменить это будет нельзя.")
    return "\n".join(lines)


def training_purged(removed: int) -> str:
    if not removed:
        return "🗑 Тренировка удалена. Сообщения в чате убрать не вышло — они старше 48 часов."
    return f"🗑 Тренировка удалена, из чата убрано сообщений: {removed}."
TRAINING_NOT_FOUND = "Тренировка не найдена."
TRAINING_EMPTY_LIST = "Пока пусто."
TRAINING_REMINDERS_ON = "🔔 Напоминания включены."
TRAINING_REMINDERS_OFF = "🔕 Напоминания выключены."

TRAINING_ASK_FREEFORM = (
    "Напиши одной строкой, например:\n"
    "<code>Завтра в 19:30, Центральный стадион, интервальная 6×400</code>\n\n"
    "Или жми ➕ и пройди по шагам."
)
TRAINING_ASK_DATE = "📅 Дата? <i>(завтра, 28 августа, 30.08, вторник)</i>"
TRAINING_ASK_TIME = "🕒 Время? <i>(19:30)</i>"
TRAINING_ASK_LOCATION = "📍 Место?"
TRAINING_ASK_TYPE = "🔥 Тип тренировки? <i>(интервальная, темповая, кросс, забег)</i>"
WEATHER_UNAVAILABLE = (
    "Прогноз недоступен: либо сервис молчит, либо дата дальше двух недель. "
    "Впиши погоду вручную."
)
TRAINING_ASK_WEATHER = "🌦️ Погода? <i>(около 25°C, возможен дождь)</i>"
TRAINING_ASK_PLAN = "📋 План — по пункту на строку. Буллеты поставлю сам."
TRAINING_ASK_GEAR = "🎒 Что взять — по пункту на строку."
TRAINING_ASK_URL = "🔗 Ссылка на локацию <i>(2ГИС, карты)</i>. «-» чтобы убрать."
TRAINING_ASK_NOTES = "❗️ Заметки: платный вход, предупреждения. По абзацу на строку."
TRAINING_ASK_DESCRIPTION = "📝 Описание? <i>(6×400, или «-» чтобы пропустить)</i>"
TRAINING_BAD_DATE = "Не понял дату. Попробуй «завтра», «28 августа» или «30.08»."
TRAINING_BAD_TIME = "Не понял время. Нужно вроде «19:30»."


def training_parse_failed(missing: tuple[str, ...]) -> str:
    return f"Не хватает: <b>{esc(', '.join(missing))}</b>.\n\n" + TRAINING_ASK_FREEFORM


def rsvp_counts_line(counts: dict[str, int]) -> str:
    return " · ".join(
        f"{RSVP_LABELS[key]} — {counts.get(key, 0)}" for key in ("going", "maybe", "not_going")
    )


def training_reminder(
    *, club: str, clock: str, location: str, training_type: str, hours: int
) -> str:
    # «Скоро» за сутки звучит враньём, «сегодня» за 24 часа — тем более.
    if hours >= 20:
        when = "Завтра"
    elif hours <= 6:
        when = "Сегодня"
    else:
        when = "Уже скоро"
    lines = [
        "🏃 <b>Напоминаем!</b>",
        "",
        f"{when} в <b>{esc(clock)}</b> тренировка {esc(club)}.",
        "",
        f"📍 {esc(location)}",
    ]
    if training_type:
        lines.append(f"🔥 {esc(training_type)}")
    lines += ["", "До встречи! 🐐"]
    return "\n".join(lines)


def training_participants(
    *, day: str, clock: str, going: list[str], maybe: list[str], not_going: list[str]
) -> str:
    def block(title: str, people: list[str]) -> str:
        if not people:
            return f"{title}: 0"
        numbered = "\n".join(f"{i}. {esc(n)}" for i, n in enumerate(people, start=1))
        return f"{title}: <b>{len(people)}</b>\n{numbered}"

    return "\n\n".join(
        [
            f"🏃 <b>Тренировка — {esc(day)}, {esc(clock)}</b>",
            block("💪 Будут", going),
            block("🤔 Возможно", maybe),
            block("❌ Не будут", not_going),
            f"<i>Всего ответили: {len(going) + len(maybe) + len(not_going)}</i>",
        ]
    )


def training_line(*, day: str, clock: str, location: str, training_type: str, going: int) -> str:
    tail = f" · {esc(training_type)}" if training_type else ""
    return f"<b>{esc(day)}, {esc(clock)}</b> · {esc(location)}{tail} · 💪 {going}"


def my_training_stats(going: int, maybe: int, skipped: int) -> str:
    return (
        "<b>📊 Твоя статистика по тренировкам</b>\n\n"
        f"💪 Отметился «буду»: {going}\n"
        f"🤔 «Возможно»: {maybe}\n"
        f"❌ «Не буду»: {skipped}"
    )


def hub_text(
    club: str,
    is_judge: bool,
    is_admin: bool,
    trainings_on: bool,
    launch: str | None = None,
) -> str:
    """Экран входа в личке. Лига — главное, тренировки идут довеском."""
    blocks = [f"🐐 <b>{esc(club)} League</b> — лига челленджей."]
    if launch:
        blocks.append(launch_notice(launch))
    blocks += [
        "Каждый день выполняешь задание и присылаешь кружок в беседу. "
        "Серия растёт, в конце месяца побеждает тот, у кого больше "
        "зачтённых кружков.\n"
        "/rules · /stats · /top · /judges",
    ]
    if trainings_on:
        blocks.append(
            "🏃 <b>Тренировки клуба</b>\n"
            "<i>Бот заодно уведомляет о них:</i> расписание, сбор «кто идёт», "
            "напоминания за сутки и за три часа.\n"
            "Скриншот Стравы ответом на пост — и приход идёт в рейтинг.\n"
            "/next · /schedule · /attendance · /mytrainings"
        )
    if is_judge:
        blocks.append("⚖️ <b>Судейство</b>\n/queue · /pending · /undo")
    if is_admin:
        blocks.append(
            "🛠 <b>Админу</b>\n"
            "/trainings — создать тренировку (можно просто написать текстом)\n"
            "/dashboard · /export · /backup · /chatid"
        )
    blocks.append("<i>Все команды — /help</i>")
    return "\n\n".join(blocks)


# ── приходы на тренировку (скриншот Стравы) ──────────────────────

CHECKIN_GONE = "Отметка не найдена."
CHECKIN_NO_TRAINING = (
    "Это не пост тренировки. Скриншот нужно отправить <b>ответом</b> "
    "на сообщение с тренировкой."
)


def checkin_accepted(mention: str, day: str, clock: str, visits: int) -> str:
    """Сразу говорим, к какой тренировке приход и сколько их всего: в общем
    топике отчётов иначе непонятно, что именно засчиталось."""
    return (
        f"🏃 {mention}, приход засчитан — {esc(day)}, {esc(clock)}.\n"
        f"Всего тренировок: <b>{visits}</b>"
    )


def checkin_no_training(mention: str) -> str:
    """Отказ мягкий: человек мог просто выложить фото в топик."""
    return (
        f"{mention}, не нашёл тренировку, к которой это отнести — "
        "за последние двое суток их не было или приход уже засчитан.\n"
        "Если тренировка была, ответь скриншотом на её пост в «Тренировках»."
    )


def checkin_too_early(mention: str, day: str, clock: str) -> str:
    """Дату называем прямо: пост часто висит с прошлой недели, и человеку
    непонятно, почему скриншот не приняли."""
    return (
        f"{mention}, эта тренировка ещё не началась — она {esc(day)} в {esc(clock)}. "
        "Скриншот присылай после неё, ответом на этот же пост."
    )


def checkin_already_counted(mention: str) -> str:
    return f"{mention}, приход на эту тренировку уже засчитан."


def checkin_approved(mention: str, visits: int, judge: str) -> str:
    return (
        f"✅ {mention}, приход засчитан.\n"
        f"Всего тренировок: <b>{visits}</b> 🏃\n"
        f"<i>Судья: {esc(judge)}</i>"
    )


def checkin_rejected(mention: str, reason: str, judge: str) -> str:
    return (
        f"❌ {mention}, зачёт по приходу отменён: {esc(reason)}.\n"
        "Пришли другой скриншот — он снова пойдёт в зачёт.\n"
        f"<i>Судья: {esc(judge)}</i>"
    )


def checkin_card(
    *,
    name: str,
    username: str | None,
    telegram_id: int,
    day: str,
    clock: str,
    location: str,
    visits: int,
) -> str:
    handle = f" (@{esc(username)})" if username else ""
    return (
        f"📸 <b>Приход</b> · {esc(name)}{handle}\n"
        f"id <code>{telegram_id}</code>\n"
        f"Тренировка: {esc(day)}, {esc(clock)}\n"
        f"📍 {esc(location)}\n"
        f"Всего засчитано ранее: {visits}"
    )


def attendance_top(month: str | None, lines: list[str]) -> str:
    head = (
        f"<b>🏃 Приходы за {esc(month)}</b>" if month else "<b>🏃 Приходы за всё время</b>"
    )
    return head + "\n<i>по подтверждённым скриншотам</i>\n\n" + "\n".join(lines)


def attendance_line(place: int, name: str, visits: int, is_me: bool = False) -> str:
    medal = {1: "🐐", 2: "🥈", 3: "🥉"}.get(place, f"{place}.")
    word = plural_visits(visits)
    line = f"{medal} {esc(name)} — {visits} {word}"
    return f"<b>{line}</b>" if is_me else line


def plural_visits(n: int) -> str:
    from bot.utils.timeutil import plural_ru

    return plural_ru(n, "тренировка", "тренировки", "тренировок")


ATTENDANCE_EMPTY = "Пока никто не отметился. Скриншот Стравы — в топик «Приходы»."
CHECKINS_QUEUE_EMPTY = "За сегодня приходов ещё не было."
CHECKINS_PENDING = "Приходов за сегодня: <b>{count}</b>. Все засчитаны."
CHECKIN_ALREADY_OK = "Приход и так засчитан — подтверждать нечего."


# ── клубы (несколько групп) ──────────────────────────────────────

NEWCLUB_IN_GROUP = (
    "Эту команду надо отправить <b>в самой группе</b>, а в форуме — "
    "в том топике, куда будут присылать кружки."
)
CLUBS_EMPTY = "Клубов пока нет. Отправь /newclub в нужной группе."


def club_already(title: str) -> str:
    return f"Эта группа уже заведена как «{esc(title)}»."


def club_created(title: str, thread_id: int | None, start_date) -> str:
    """Сразу говорим, что настроено, а что нет: топики тренировок и приходов
    задаются отдельно, и без них половина бота промолчит."""
    where = f"топик <code>{thread_id}</code>" if thread_id else "вся группа"
    return (
        f"✅ Клуб «{esc(title)}» заведён.\n"
        f"Кружки принимаю тут: {where}.\n"
        f"Ты в нём админ и судья.\n\n"
        f"Свой челлендж создан, старт — {start_date.strftime('%d.%m.%Y')}. "
        "Участники жмут /start прямо тут.\n\n"
        "Дальше по желанию: топики тренировок и приходов, свой чат судей. "
        "Скажи, какие — настрою."
    )


def clubs_list(rows: list[tuple[str, int, int, int]]) -> str:
    lines = ["<b>🏛 Клубы</b>", ""]
    for title, chat_id, thread_id, judges in rows:
        thread = f" · топик {thread_id}" if thread_id else ""
        lines.append(f"• <b>{esc(title)}</b> — <code>{chat_id}</code>{thread} · судей: {judges}")
    return "\n".join(lines)


NO_PRIZES = (
    "Призов пока не объявляли. Если есть что предложить — напиши админу, "
    "он добавит их командой /setclub."
)


SETCLUB_NO_CLUB = (
    "Эта группа ещё не заведена. Отправь /newclub в том топике, "
    "куда будут присылать кружки."
)
SETCLUB_NEED_VALUE = "После названия поля нужен текст. Пример: <code>/setclub task планка минуту</code>"


def setclub_help(title: str, task: str, prizes: str) -> str:
    return (
        f"<b>⚙️ Клуб «{esc(title)}»</b>\n\n"
        f"<b>Задание:</b> {esc(task) if task else '<i>общее из настроек бота</i>'}\n"
        f"<b>Призы:</b> {'заданы' if prizes else '<i>нет</i>'}\n\n"
        "<b>Что можно поменять</b>\n"
        "<code>/setclub task ...</code> — задание челленджа\n"
        "<code>/setclub prizes ...</code> — призы (пустое значение уберёт блок)\n"
        "<code>/setclub name ...</code> — название клуба\n\n"
        "<b>Топики</b> — отправь команду <b>внутри нужной ветки</b>, без текста:\n"
        "<code>/setclub circles</code> — сюда присылают кружки\n"
        "<code>/setclub trainings</code> — сюда постятся тренировки\n"
        "<code>/setclub checkins</code> — сюда шлют скриншоты Стравы\n"
        "<code>/setclub judges</code> — этот чат станет чатом судей"
    )


def setclub_done(field: str, thread_id: int, chat_id: int) -> str:
    where = {
        "circles": "кружки", "кружки": "кружки",
        "trainings": "тренировки", "тренировки": "тренировки",
        "checkins": "приходы", "приходы": "приходы",
    }
    if field in where:
        spot = f"топик <code>{thread_id}</code>" if thread_id else "вся группа"
        return f"✅ {where[field].capitalize()} теперь тут: {spot}."
    if field in {"judges", "судьи"}:
        return f"✅ Чат судей: <code>{chat_id}</code>."
    return "✅ Сохранил."
