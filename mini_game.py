import random
import logging
import traceback
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request, session, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from models import db, User, Config
from best_setup_voting import send_token_reward as voting_send_token_reward
import math

# Создаем локальный логгер для данного модуля
logger = logging.getLogger(__name__)

mini_game_bp = Blueprint("mini_game_bp", __name__, template_folder="templates")

# Для упрощенной физики мы добавим простой velocity и damping
class Player:
    def __init__(self, mesh):
        self.mesh = mesh
        self.velocity = [0, 0, 0]
        self.damping = 0.9  # коэффициент затухания
        self.speed = 5

    def update(self, delta):
        # Обновляем положение с учетом скорости и затухания
        for i in range(3):
            self.velocity[i] *= self.damping
        self.mesh.position.x += self.velocity[0] * delta
        self.mesh.position.y += self.velocity[1] * delta
        self.mesh.position.z += self.velocity[2] * delta

# Глобальные переменные (будут инициализированы в JS, здесь для описания API не требуются)
# Функции API сервера для мини-игры (статус игры, угадывание направления и распределение очков) остаются без изменений

@mini_game_bp.route('/retro-game', methods=['GET'])
def retro_game():
    """
    Возвращает страницу с 3D-игрой. Если пользователь авторизован, ему показывается страница с 3D‑сценой,
    где персонаж перемещается по улицам Wall Street, не проходит сквозь здания (будет учтена простая коллизия),
    а при приближении к терминалу или к интерактивному NPC «Дядя Джон» запускается мини‑игра (график свечей).
    """
    if 'user_id' not in session:
        flash("Пожалуйста, войдите в систему.", "warning")
        return redirect(url_for('login'))
    return render_template('mini_game.html')

@mini_game_bp.route('/api/game_status', methods=['GET'])
def game_status():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session['user_id']
    record = db.session.execute(
        "SELECT * FROM user_game_score WHERE user_id = :uid", {"uid": user_id}
    ).fetchone()
    if not record:
        return jsonify({"times_played_today": 0, "weekly_points": 0}), 200
    return jsonify({
        "times_played_today": record["times_played_today"],
        "weekly_points": record["weekly_points"]
    }), 200

@mini_game_bp.route('/api/guess_direction', methods=['POST'])
def guess_direction():
    try:
        csrf_token = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing"}), 400
        validate_csrf(csrf_token)
    except CSRFError:
        return jsonify({"error": "CSRF token invalid"}), 400

    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user_guess = request.form.get('direction', '').strip().lower()
    if user_guess not in ['up', 'down']:
        return jsonify({"error": "Invalid guess (must be 'up' or 'down')"}), 400

    row = db.session.execute(
        "SELECT * FROM user_game_score WHERE user_id = :uid", {"uid": user_id}
    ).fetchone()
    if row is None:
        db.session.execute(
            "INSERT INTO user_game_score (user_id, weekly_points, times_played_today, last_played_date) VALUES (:uid, 0, 0, CURRENT_DATE)",
            {"uid": user_id}
        )
        db.session.commit()
        row = db.session.execute(
            "SELECT * FROM user_game_score WHERE user_id = :uid", {"uid": user_id}
        ).fetchone()

    times_played_today = row["times_played_today"]
    last_played_date = row["last_played_date"]
    today_date = datetime.utcnow().date()
    if last_played_date is None or last_played_date < today_date:
        times_played_today = 0

    if times_played_today >= 5:
        return jsonify({"error": "Daily limit reached (5 plays per day)."}), 400

    real_direction = random.choice(['up', 'down'])
    is_correct = (user_guess == real_direction)
    points_earned = 1 if is_correct else 0
    new_weekly_points = row["weekly_points"] + points_earned
    new_times_played_today = times_played_today + 1

    db.session.execute("""
        UPDATE user_game_score
           SET weekly_points = :wpts,
               times_played_today = :tp,
               last_played_date = :ld
         WHERE user_id = :uid
    """, {"wpts": new_weekly_points, "tp": new_times_played_today, "ld": today_date, "uid": user_id})
    db.session.commit()

    return jsonify({
        "result": "correct" if is_correct else "wrong",
        "real_direction": real_direction,
        "points_earned": points_earned,
        "weekly_points": new_weekly_points,
        "times_played_today": new_times_played_today
    }), 200

def distribute_game_rewards():
    """
    Еженедельное распределение наград: функция смотрит значение в конфигурации (ключ 'game_rewards_pool_size'),
    затем делит пул пропорционально набранным weekly_points у всех игроков,
    отправляет награды через voting_send_token_reward и обнуляет weekly_points.
    """
    try:
        cfg = Config.query.filter_by(key='game_rewards_pool_size').first()
        if not cfg:
            logger.warning("[mini_game] No config 'game_rewards_pool_size' found, pool=0.")
            pool = 0.0
        else:
            try:
                pool = float(cfg.value)
            except:
                pool = 0.0
        if pool <= 0:
            logger.info("[mini_game] game_rewards_pool_size <= 0, skipping distribution.")
            return

        row_sum = db.session.execute("SELECT SUM(weekly_points) AS total_points FROM user_game_score").fetchone()
        total_points = row_sum["total_points"] if row_sum and row_sum["total_points"] else 0
        if total_points <= 0:
            logger.info("[mini_game] total_points=0, no participants.")
            return

        data = db.session.execute("""
            SELECT ugs.user_id, ugs.weekly_points, "user".wallet_address
              FROM user_game_score ugs
              JOIN "user" ON "user".id = ugs.user_id
             WHERE ugs.weekly_points > 0
        """).fetchall()
        for row in data:
            user_id = row["user_id"]
            wpts = row["weekly_points"]
            wallet = row["wallet_address"] or ""
            if not wallet:
                continue
            share = pool * (wpts / total_points)
            if share <= 0:
                continue
            success = voting_send_token_reward(wallet, share)
            if success:
                logger.info(f"[mini_game] Sent {share:.4f} UJO to user_id={user_id}")
            else:
                logger.error(f"[mini_game] Could NOT send tokens to user_id={user_id}")
        db.session.execute("UPDATE user_game_score SET weekly_points=0")
        db.session.commit()
        logger.info("[mini_game] Weekly points reset after distribution.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"[mini_game] distribute_game_rewards error: {e}", exc_info=True)
