from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from app.dependencies import get_db
from app.models.user import Student
from app.models.lesson import LessonCompletion, Lesson
from app.models.exercise import ExerciseSubmission, Exercise
from app.models.submission import Submission
from app.models.project import Project
from app.models.course import Course, student_courses
from app.models.ranking import Ranking
from app.models.achievement import Achievement
from app.models.student_achievement import StudentAchievement

router = APIRouter()

_TZ = timezone(timedelta(hours=5))  # Tashkent UTC+5


def _day_start() -> datetime:
    now = datetime.now(_TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _week_start() -> datetime:
    now = datetime.now(_TZ)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _month_start() -> datetime:
    now = datetime.now(_TZ)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


@router.get("/search-student")
async def search_student(q: str, db: AsyncSession = Depends(get_db)):
    if len(q.strip()) < 2:
        return []
    results = await db.execute(
        select(Student).where(
            (Student.full_name.ilike(f"%{q}%")) |
            (Student.username.ilike(f"%{q}%"))
        ).limit(10)
    )
    students = results.scalars().all()
    return [
        {"id": s.id, "name": s.full_name or s.username or f"Student #{s.id}"}
        for s in students
    ]


@router.get("/student-stats/{student_id}")
async def get_student_stats(student_id: int, db: AsyncSession = Depends(get_db)):
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Enrolled courses
    enrolled_q = await db.execute(
        select(Course).join(
            student_courses,
            Course.id == student_courses.c.course_id
        ).where(student_courses.c.student_id == student_id)
    )
    courses = enrolled_q.scalars().all()
    course_ids = [c.id for c in courses]

    # Lessons per course
    lessons_by_course: dict = {}
    if course_ids:
        total_q = await db.execute(
            select(Lesson.course_id, func.count(Lesson.id))
            .where(Lesson.course_id.in_(course_ids))
            .group_by(Lesson.course_id)
        )
        for cid, cnt in total_q.all():
            lessons_by_course[cid] = {"total": cnt, "completed": 0}
        done_q = await db.execute(
            select(Lesson.course_id, func.count(LessonCompletion.id))
            .join(LessonCompletion, Lesson.id == LessonCompletion.lesson_id)
            .where(
                LessonCompletion.student_id == student_id,
                Lesson.course_id.in_(course_ids)
            )
            .group_by(Lesson.course_id)
        )
        for cid, cnt in done_q.all():
            if cid in lessons_by_course:
                lessons_by_course[cid]["completed"] = cnt

    # Exercise stats per course
    exercises_by_course: dict = {}
    if course_ids:
        ex_q = await db.execute(
            select(
                Lesson.course_id,
                func.count(ExerciseSubmission.id),
                func.sum(case((ExerciseSubmission.is_correct == True, 1), else_=0))
            )
            .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
            .join(Lesson, Lesson.id == Exercise.lesson_id)
            .where(
                ExerciseSubmission.student_id == student_id,
                Lesson.course_id.in_(course_ids)
            )
            .group_by(Lesson.course_id)
        )
        for cid, total, correct in ex_q.all():
            exercises_by_course[cid] = {"total": total, "correct": int(correct or 0)}

    # Project submissions per course — read status/grade from projects table
    # because submit_project only updates projects.status, not submissions.status
    projects_by_course: dict = {}
    if course_ids:
        sub_q = await db.execute(
            select(Lesson.course_id, Project.status, Project.grade,
                   Project.points_earned, Lesson.title)
            .join(Submission, Submission.lesson_id == Lesson.id)
            .join(Project, Project.id == Submission.project_id)
            .where(
                Submission.student_id == student_id,
                Lesson.course_id.in_(course_ids)
            )
            .order_by(Lesson.course_id)
        )
        for cid, status, grade, pts, lesson_title in sub_q.all():
            projects_by_course.setdefault(cid, []).append({
                "lesson": lesson_title,
                "status": status,
                "grade": grade,
                "points": pts,
            })

    # Ranking (for total_points and global_rank only — period aggregates unreliable)
    ranking_q = await db.execute(
        select(Ranking).where(Ranking.student_id == student_id)
    )
    ranking = ranking_q.scalar_one_or_none()

    day_start = _day_start()
    week_start = _week_start()
    month_start = _month_start()

    # Daily stats: exercise score sum + lesson count today
    daily_ex_q = await db.execute(
        select(
            func.coalesce(func.sum(ExerciseSubmission.score), 0),
            func.count(ExerciseSubmission.id),
            func.sum(case((ExerciseSubmission.is_correct == True, 1), else_=0))
        )
        .where(ExerciseSubmission.student_id == student_id,
               ExerciseSubmission.submitted_at >= day_start)
    )
    daily_score, daily_ex_total, daily_ex_correct = daily_ex_q.one()

    daily_lessons_q = await db.execute(
        select(func.count(LessonCompletion.id))
        .where(LessonCompletion.student_id == student_id,
               LessonCompletion.completed_at >= day_start)
    )
    daily_lessons = daily_lessons_q.scalar() or 0

    # Weekly stats: since Monday
    weekly_ex_q = await db.execute(
        select(
            func.coalesce(func.sum(ExerciseSubmission.score), 0),
            func.count(ExerciseSubmission.id),
            func.sum(case((ExerciseSubmission.is_correct == True, 1), else_=0))
        )
        .where(ExerciseSubmission.student_id == student_id,
               ExerciseSubmission.submitted_at >= week_start)
    )
    weekly_score, w_ex_total, w_ex_correct = weekly_ex_q.one()

    weekly_lessons_q = await db.execute(
        select(func.count(LessonCompletion.id))
        .where(LessonCompletion.student_id == student_id,
               LessonCompletion.completed_at >= week_start)
    )
    weekly_lessons = weekly_lessons_q.scalar() or 0

    # Monthly stats: since 1st of month
    monthly_ex_q = await db.execute(
        select(
            func.coalesce(func.sum(ExerciseSubmission.score), 0),
            func.count(ExerciseSubmission.id),
            func.sum(case((ExerciseSubmission.is_correct == True, 1), else_=0))
        )
        .where(ExerciseSubmission.student_id == student_id,
               ExerciseSubmission.submitted_at >= month_start)
    )
    monthly_score, m_ex_total, m_ex_correct = monthly_ex_q.one()

    monthly_lessons_q = await db.execute(
        select(func.count(LessonCompletion.id))
        .where(LessonCompletion.student_id == student_id,
               LessonCompletion.completed_at >= month_start)
    )
    monthly_lessons = monthly_lessons_q.scalar() or 0

    # Last 3 achievements earned by the student
    ach_q = await db.execute(
        select(Achievement.name, Achievement.icon)
        .join(StudentAchievement, StudentAchievement.achievement_id == Achievement.id)
        .where(StudentAchievement.student_id == student_id)
        .order_by(StudentAchievement.earned_at.desc())
        .limit(3)
    )
    recent_achievements = [
        {"name": name, "icon": icon or "🏅"}
        for name, icon in ach_q.all()
    ]

    courses_data = []
    for c in courses:
        cid = c.id
        lesson_info = lessons_by_course.get(cid, {"total": 0, "completed": 0})
        courses_data.append({
            "id": cid,
            "title": c.title,
            "lessons_total": lesson_info["total"],
            "lessons_completed": lesson_info["completed"],
            "exercises": exercises_by_course.get(cid, {"total": 0, "correct": 0}),
            "projects": projects_by_course.get(cid, []),
        })

    return {
        "student_id": student_id,
        "name": student.full_name or student.username or "",
        "total_points": ranking.total_points if ranking else 0,
        "global_rank": ranking.global_rank if ranking else 0,
        # Period points computed from exercise scores (ranking table aggregates unreliable)
        "daily_points": int(daily_score or 0),
        "daily_lessons": daily_lessons,
        "daily_exercises": {
            "total": int(daily_ex_total or 0),
            "correct": int(daily_ex_correct or 0),
        },
        "weekly_points": int(weekly_score or 0),
        "weekly_rank": ranking.weekly_rank if ranking else 0,
        "weekly_lessons": weekly_lessons,
        "weekly_exercises": {
            "total": int(w_ex_total or 0),
            "correct": int(w_ex_correct or 0),
        },
        "monthly_points": int(monthly_score or 0),
        "monthly_rank": ranking.monthly_rank if ranking else 0,
        "monthly_lessons": monthly_lessons,
        "monthly_exercises": {
            "total": int(m_ex_total or 0),
            "correct": int(m_ex_correct or 0),
        },
        "courses": courses_data,
        "achievements": recent_achievements,
    }


@router.get("/weekly-rankings")
async def get_weekly_rankings(db: AsyncSession = Depends(get_db)):
    """Global weekly leaderboard for the Sunday report.

    Returns all students ranked by:
    - weekly_exercise_points: SUM of exercise_submissions.score since Monday (Tashkent)
    - project_points: SUM of projects.points_earned WHERE status='Approved' (all-time)
    """
    week_start = _week_start()

    # Weekly exercise ranking — all students with score > 0 this week
    ex_q = await db.execute(
        select(
            ExerciseSubmission.student_id,
            Student.full_name,
            func.coalesce(func.sum(ExerciseSubmission.score), 0).label("pts"),
        )
        .join(Student, Student.id == ExerciseSubmission.student_id)
        .where(ExerciseSubmission.submitted_at >= week_start)
        .group_by(ExerciseSubmission.student_id, Student.full_name)
        .order_by(func.sum(ExerciseSubmission.score).desc())
    )
    exercise_ranking = []
    for rank, (sid, name, pts) in enumerate(ex_q.all(), start=1):
        exercise_ranking.append({
            "rank": rank,
            "student_id": sid,
            "name": name or f"Student #{sid}",
            "weekly_points": int(pts),
        })

    # Project ranking — all-time approved project points
    proj_q = await db.execute(
        select(
            Project.student_id,
            Student.full_name,
            func.count(Project.id).label("approved_count"),
            func.coalesce(func.sum(Project.points_earned), 0).label("pts"),
        )
        .join(Student, Student.id == Project.student_id)
        .where(Project.status == "Approved")
        .group_by(Project.student_id, Student.full_name)
        .order_by(func.sum(Project.points_earned).desc())
    )
    project_ranking = []
    for rank, (sid, name, approved, pts) in enumerate(proj_q.all(), start=1):
        project_ranking.append({
            "rank": rank,
            "student_id": sid,
            "name": name or f"Student #{sid}",
            "approved_count": int(approved),
            "total_points": int(pts),
        })

    return {
        "exercise_ranking": exercise_ranking,
        "project_ranking": project_ranking,
    }
