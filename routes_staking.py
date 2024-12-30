# routes_staking.py

import logging
import traceback
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from flask_wtf.csrf import validate_csrf, CSRFError
from models import db, User, UserStaking
from staking_logic import confirm_staking_tx
from best_setup_voting import send_token_reward

logger = logging.getLogger(__name__)

staking_bp = Blueprint('staking_bp', __name__)

@staking_bp.route('/confirm', methods=['POST'])
def confirm_staking():
    """
    Фронтенд (MetaMask) после успешной транзакции вызывает:
      POST /staking/confirm  { txHash: '0x123...' }

    Здесь мы проверяем txHash через confirm_staking_tx(...)
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/confirm.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Пользователь с ID {user_id} не найден.")
            return jsonify({"error": "User not found"}), 404

        data = request.get_json() or {}
        tx_hash = data.get("txHash")
        if not tx_hash:
            logger.warning("txHash не предоставлен в запросе.")
            return jsonify({"error": "No txHash provided"}), 400

        # Валидация формата txHash (простейшая проверка)
        if not isinstance(tx_hash, str) or not tx_hash.startswith('0x') or len(tx_hash) != 66:
            logger.warning(f"Некорректный формат txHash: {tx_hash}")
            return jsonify({"error": "Invalid txHash format."}), 400

        logger.info(f"Пользователь ID {user_id} отправил txHash: {tx_hash}")

        ok = confirm_staking_tx(user, tx_hash)
        if ok:
            logger.info(f"Стейкинг подтверждён для пользователя ID {user_id} с txHash {tx_hash}.")
            return jsonify({"status": "success"}), 200
        else:
            logger.error(f"Стейкинг подтверждён не был для пользователя ID {user_id} с txHash {tx_hash}.")
            return jsonify({"error": "Staking confirm failed"}), 400

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при подтверждении стейкинга: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500
        
@staking_bp.route('/set_wallet', methods=['POST'])
def set_wallet():
    try:
        wallet_address = request.form.get('wallet_address')
        if not wallet_address or not wallet_address.startswith('0x') or len(wallet_address) != 42:
            logger.warning(f"Некорректный адрес кошелька: {wallet_address}")
            return jsonify({"error": "Invalid wallet address."}), 400

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/set_wallet.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Пользователь с ID {user_id} не найден.")
            return jsonify({"error": "User not found."}), 404

        user.wallet_address = wallet_address
        db.session.commit()
        logger.info(f"Адрес кошелька пользователя ID {user_id} обновлён на {wallet_address}.")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при установке адреса кошелька: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/get_user_stakes', methods=['GET'])
def get_user_stakes():
    """
    Возвращает JSON со списком UserStaking для текущего пользователя
    (чтобы отобразить в subscription.html).
    """
    if 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /staking/get_user_stakes.")
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
    logger.info(f"Отправлены {len(result)} стейков для пользователя ID {user_id}.")
    return jsonify({"stakes": result}), 200


@staking_bp.route('/claim_staking_rewards', methods=['POST'])
def claim_staking_rewards():
    """
    Пользователь жмёт "Claim". 
    Логика: отправляем pending_rewards на user.wallet_address, 
    обнуляем pending_rewards.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/claim_staking_rewards.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.wallet_address:
            logger.warning(f"Пользователь ID {user_id} не найден или не имеет кошелька.")
            return jsonify({"error": "No wallet"}), 400

        stakes = UserStaking.query.filter_by(user_id=user_id).all()
        total_claim = 0.0
        for s in stakes:
            if s.pending_rewards > 0:
                total_claim += s.pending_rewards
                s.pending_rewards = 0.0

        if total_claim <= 0.0:
            logger.info(f"Пользователь ID {user_id} не имеет наград для клейма.")
            return jsonify({"error": "Нет наград для клейма."}), 400

        logger.info(f"Пользователь ID {user_id} хочет клеймить {total_claim:.4f} UJO.")

        # Отправка через send_token_reward (из best_setup_voting)
        success = send_token_reward(user.wallet_address, total_claim)
        if not success:
            logger.error(f"Отправка наград не удалась для пользователя ID {user_id}.")
            # откатываем
            db.session.rollback()
            return jsonify({"error": "send_token_reward failed"}), 400

        db.session.commit()
        logger.info(f"Награды {total_claim:.4f} UJO успешно отправлены пользователю ID {user_id}.")
        return jsonify({"message": f"Claimed {total_claim:.4f} UJO."}), 200

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при клейме наград: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/unstake_staking', methods=['POST'])
def unstake_staking():
    """
    Пользователь жмёт "Unstake".
    Логика: проверяем, можно ли unstake (unlocked_at <= now).
    Возвращаем стейк. 1% удержание.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/unstake_staking.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.wallet_address:
            logger.warning(f"Пользователь ID {user_id} не найден или не имеет кошелька.")
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
            logger.info(f"Пользователь ID {user_id} не имеет доступных стейков для вывода.")
            return jsonify({"error": "Нет доступных стейков для вывода (либо ещё не прошло 30 дней)."}), 400

        # Удержим 1%
        unstake_after_fee = total_unstake * 0.99
        fee = total_unstake * 0.01

        logger.info(f"Пользователь ID {user_id} выводит {total_unstake:.4f} UJO (сбор 1%: {fee:.4f} UJO).")

        success = send_token_reward(user.wallet_address, unstake_after_fee)
        if not success:
            logger.error(f"Отправка стейка не удалась для пользователя ID {user_id}.")
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
            logger.info(f"Премиум статус пользователя ID {user_id} отключен из-за отсутствия активных стейков.")

        db.session.commit()
        logger.info(f"Стейк {unstake_after_fee:.4f} UJO успешно отправлен пользователю ID {user_id}.")
        return jsonify({"message": f"Unstaked total: {total_unstake:.4f} (1% fee). You received ~{unstake_after_fee:.4f} UJO."}), 200

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при unstake_staking: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500
