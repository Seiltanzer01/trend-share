# mini_game.py

import random
import logging
import traceback
import pytz
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request, session, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from app import db, logger
from models import User, Config
from web3 import Web3
from best_setup_voting import send_token_reward as voting_send_token_reward  # используем ту же функцию наград
import math

mini_game_bp = Blueprint("mini_game_bp", __name__, template_folder="templates")

### ----------------------------------------------------------------
### 1) Модельные данные хранятся в таблице user_game_score,
###    которую мы создадим без миграций в initialize().
### ----------------------------------------------------------------

@mini_game_bp.route('/retro-game', methods=['GET'])
def retro_game():
    """
    Страница с ретро-платформером, где трейдер бегает по Уолл-стрит
    и может подойти к терминалу/графику, чтобы угадать направление.
    """
    if 'user_id' not in session:
        flash("Пожалуйста, войдите в систему.", "warning")
        return redirect(url_for('login'))
    return render_template('mini_game.html')  # Этот шаблон нужно будет создать (см. ниже)

@mini_game_bp.route('/api/game_status', methods=['GET'])
def game_status():
    """
    Возвращает текущее состояние игры для пользователя:
    - сколько раз он уже сыграл сегодня
    - сколько у него очков (weekly_points)
    - лимит 5 раз в день
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session['user_id']
    # Получаем запись из user_game_score
    record = db.session.execute("""
        SELECT * FROM user_game_score WHERE user_id = :uid
    """, {"uid": user_id}).fetchone()

    if not record:
        return jsonify({
            "times_played_today": 0,
            "weekly_points": 0
        }), 200

    # Проверяем, не сменилась ли дата (если поменялась — мы в initialize() обнулим, но если user_login после этого... )
    times_played_today = record["times_played_today"]
    weekly_points = record["weekly_points"]
    return jsonify({
        "times_played_today": times_played_today,
        "weekly_points": weekly_points
    }), 200

@mini_game_bp.route('/api/guess_direction', methods=['POST'])
def guess_direction():
    """
    Пользователь пытается угадать направление (Up/Down) для следующих 10 свечей.
    Считаем это упрощённо случайным образом. При правильном ответе +1 очко.
    Можно играть до 5 раз в день.
    """
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
    user_guess = request.form.get('direction', '').strip().lower()  # 'up' или 'down'
    if user_guess not in ['up', 'down']:
        return jsonify({"error": "Invalid guess (must be 'up' or 'down')"}), 400

    # Получаем/создаём запись в user_game_score
    row = db.session.execute("""
        SELECT * FROM user_game_score WHERE user_id = :uid
    """, {"uid": user_id}).fetchone()

    if row is None:
        # Вставляем новую строчку
        db.session.execute("""
            INSERT INTO user_game_score (user_id, weekly_points, times_played_today, last_played_date)
            VALUES (:uid, 0, 0, CURRENT_DATE)
        """, {"uid": user_id})
        db.session.commit()
        # Перечитываем
        row = db.session.execute("""
            SELECT * FROM user_game_score WHERE user_id = :uid
        """, {"uid": user_id}).fetchone()

    # Проверка ежедневного лимита
    times_played_today = row["times_played_today"]
    last_played_date = row["last_played_date"]  # DATE
    # Если дата сменилась — сбросим счётчик
    today_date = datetime.utcnow().date()
    if last_played_date is None or last_played_date < today_date:
        times_played_today = 0

    if times_played_today >= 5:
        return jsonify({"error": "Daily limit reached (5 plays per day)."}), 400

    # Случайно генерируем результат
    real_direction = random.choice(['up', 'down'])  # где-то 50/50
    is_correct = (user_guess == real_direction)
    points_earned = 1 if is_correct else 0

    new_weekly_points = row["weekly_points"] + points_earned
    new_times_played_today = times_played_today + 1

    # Обновляем запись
    db.session.execute("""
        UPDATE user_game_score
           SET weekly_points = :wpts,
               times_played_today = :tp,
               last_played_date = :ld
         WHERE user_id = :uid
    """, {
        "wpts": new_weekly_points,
        "tp": new_times_played_today,
        "ld": today_date,
        "uid": user_id
    })
    db.session.commit()

    return jsonify({
        "result": "correct" if is_correct else "wrong",
        "real_direction": real_direction,
        "points_earned": points_earned,
        "weekly_points": new_weekly_points,
        "times_played_today": new_times_played_today
    }), 200

### ----------------------------------------------------------------
### 2) Еженедельная выплата: в воскресенье ночью (или любой день/время),
###    распределяем game_rewards_pool между всеми игроками по их weekly_points.
### ----------------------------------------------------------------

def distribute_game_rewards():
    """
    Смотрим Config(key='game_rewards_pool_size'), делим пропорционально weekly_points,
    рассылаем награды (voting_send_token_reward), обнуляем weekly_points.
    """
    try:
        # Ищем в таблице config запись с key='game_rewards_pool_size'
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
            logger.info("[mini_game] game_rewards_pool_size <= 0, пропускаем.")
            return

        # Суммируем weekly_points
        rows = db.session.execute("SELECT SUM(weekly_points) AS total_points FROM user_game_score").fetchone()
        total_points = rows["total_points"] if rows and rows["total_points"] else 0
        if total_points <= 0:
            logger.info("[mini_game] total_points=0, никто не играл.")
            return

        # Получаем список (user_id, weekly_points, user.wallet_address)
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
                # Если у пользователя нет кошелька - пропускаем
                continue
            share = pool * (wpts / total_points)
            if share <= 0:
                continue

            # Отправляем токены
            success = voting_send_token_reward(wallet, share)
            if success:
                logger.info(f"[mini_game] Sent {share:.4f} UJO to user_id={user_id}")
            else:
                logger.error(f"[mini_game] Could NOT send tokens to user_id={user_id}")

        # Обнуляем weekly_points
        db.session.execute("UPDATE user_game_score SET weekly_points=0")
        db.session.commit()
        logger.info("[mini_game] Weekly points reset after distribution.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"[mini_game] distribute_game_rewards error: {e}", exc_info=True)
