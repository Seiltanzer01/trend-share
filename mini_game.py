import random
import logging
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, session, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from models import db, User, Config
from best_setup_voting import send_token_reward as voting_send_token_reward
import math

logger = logging.getLogger(__name__)
mini_game_bp = Blueprint("mini_game_bp", __name__, template_folder="templates")

@mini_game_bp.route('/retro-game', methods=['GET'])
def retro_game():
    if 'user_id' not in session:
        flash("Please log in.", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.wallet_address:
        flash("Для участия в игре укажите ваш кошелёк (Set Wallet).", "warning")
        return redirect(url_for('best_setup_voting.set_wallet'))
    
    # Далее рендерим нашу страницу mini_game.html
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
    # Expecting "long" or "short"
    if user_guess not in ['long', 'short']:
        return jsonify({"error": "Invalid guess (must be 'long' or 'short')"}), 400

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

    if times_played_today >= 30:  # e.g., max 30 forecasts per day (10 forecasts * 3 sessions)
        return jsonify({"error": "Daily limit reached (30 forecasts per day)."}), 400

    real_direction = random.choice(['long', 'short'])
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
    Weekly distribution of rewards: the reward pool is divided proportionally based on weekly_points.
    After distribution, weekly_points are reset.
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
