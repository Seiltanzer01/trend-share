# routes_staking.py

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from models import db, User, UserStaking
from staking_logic import confirm_staking_tx
from best_setup_voting import send_token_reward

logger = logging.getLogger(__name__)

staking_bp = Blueprint('staking_bp', __name__)


@staking_bp.route('/confirm', methods=['POST'])
def confirm_staking():
    """
    Фронтенд (Metamask) после успешной транзакции вызывает:
      POST /staking/confirm  { txHash: '0x123...' }

    Здесь мы проверяем txHash через confirm_staking_tx(...)
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    from models import User
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.json or {}
    tx_hash = data.get("txHash")
    if not tx_hash:
        return jsonify({"error": "No txHash provided"}), 400

    ok = confirm_staking_tx(user, tx_hash)
    if ok:
        return jsonify({"status": "success"}), 200
    else:
        return jsonify({"error": "Staking confirm failed"}), 400


@staking_bp.route('/get_user_stakes', methods=['GET'])
def get_user_stakes():
    """
    Возвращает JSON со списком UserStaking для текущего пользователя
    (чтобы отобразить в subscription.html).
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    stakes = UserStaking.query.filter_by(user_id=user_id).all()
    result = []
    for s in stakes:
        result.append({
            "tx_hash": s.tx_hash,
            "staked_usd": round(s.staked_usd, 2),
            "staked_amount": round(s.staked_amount, 4),
            "pending_rewards": round(s.pending_rewards, 4),
            "unlocked_at": s.unlocked_at.isoformat()
        })
    return jsonify({"stakes": result}), 200


@staking_bp.route('/claim_staking_rewards', methods=['POST'])
def claim_staking_rewards():
    """
    Пользователь жмёт "Claim". 
    Логика: отправляем pending_rewards на user.wallet_address, 
    обнуляем pending_rewards.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.wallet_address:
        return jsonify({"error": "No wallet"}), 400

    stakes = UserStaking.query.filter_by(user_id=user_id).all()
    total_claim = 0.0
    for s in stakes:
        if s.pending_rewards > 0:
            total_claim += s.pending_rewards
            s.pending_rewards = 0.0

    if total_claim <= 0.0:
        return jsonify({"error": "Нет наград для клейма."}), 400

    # Отправка через send_token_reward (из best_setup_voting)
    success = send_token_reward(user.wallet_address, total_claim)
    if not success:
        # откатываем
        db.session.rollback()
        return jsonify({"error": "send_token_reward failed"}), 400

    db.session.commit()
    return jsonify({"message": f"Claimed {total_claim:.4f} UJO."}), 200


@staking_bp.route('/unstake_staking', methods=['POST'])
def unstake_staking():
    """
    Пользователь жмёт "Unstake".
    Логика: проверяем, можно ли unstake (unlocked_at <= now).
    Возвращаем стейк. 1% удержание.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.wallet_address:
        return jsonify({"error": "No wallet"}), 400

    stakings = UserStaking.query.filter_by(user_id=user_id).all()
    total_unstake = 0.0
    now = datetime.utcnow()
    for s in stakings:
        if s.staked_amount > 0 and s.unlocked_at <= now:
            total_unstake += s.staked_amount
            s.staked_amount = 0
            s.staked_usd = 0
            s.pending_rewards = 0

    if total_unstake <= 0:
        return jsonify({"error": "Нет доступных стейков для вывода (либо ещё не прошло 30 дней)."}), 400

    # Удержим 1%
    unstake_after_fee = total_unstake * 0.99

    success = send_token_reward(user.wallet_address, unstake_after_fee)
    if not success:
        db.session.rollback()
        return jsonify({"error": "send_token_reward failed"}), 400

    # Если всё ок — возможно отключим premium, если все стейки обнулены.
    # Проверим, остались ли ещё staked_amount>0
    remaining = UserStaking.query.filter(
        UserStaking.user_id == user_id,
        UserStaking.staked_amount > 0
    ).count()
    if remaining == 0:
        user.assistant_premium = False

    db.session.commit()
    return jsonify({"message": f"Unstaked total: {total_unstake:.4f} (1% fee). You received ~{unstake_after_fee:.4f} UJO."}), 200
