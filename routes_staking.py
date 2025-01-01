# routes_staking.py

import logging
import traceback
from datetime import datetime
from flask import Blueprint, request, jsonify, session, render_template, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from models import db, User, UserStaking
from staking_logic import (
    confirm_staking_tx,
    generate_unique_wallet,
    exchange_weth_to_ujo,
    get_token_balance,
    get_token_price_in_usd,
    web3,
    token_contract,
    weth_contract,
    ujo_contract,
    PROJECT_WALLET_ADDRESS
)
from best_setup_voting import send_token_reward
from web3 import Web3  # Импорт класса Web3

logger = logging.getLogger(__name__)

staking_bp = Blueprint('staking_bp', __name__)

@staking_bp.route('/generate_wallet', methods=['POST'])
def generate_wallet():
    """
    Генерирует уникальный кошелек для пользователя.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/generate_wallet.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Пользователь с ID {user_id} не найден.")
            return jsonify({"error": "User not found."}), 404

        if user.wallet_address:
            logger.info(f"Пользователь ID {user_id} уже имеет кошелек: {user.wallet_address}")
            return jsonify({"error": "Wallet already exists.", "wallet_address": user.wallet_address}), 400

        # Генерация уникального кошелька
        wallet_address, private_key = generate_unique_wallet()

        # Сохранение кошелька в базе данных
        user.wallet_address = wallet_address
        user.private_key = private_key
        db.session.commit()

        logger.info(f"Сгенерирован кошелек для пользователя ID {user_id}: {wallet_address}")

        return jsonify({"status": "success", "wallet_address": wallet_address}), 200

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при генерации кошелька: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/deposit', methods=['GET'])
def deposit_page():
    """
    Страница для депозита токенов. Показывает адрес кошелька и инструкции.
    """
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для депозита.', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Пользователь не найден.', 'danger')
        return redirect(url_for('login'))

    if not user.wallet_address:
        flash('Сначала сгенерируйте кошелек.', 'warning')
        return redirect(url_for('staking_bp.generate_wallet_page'))

    # Здесь можно добавить дополнительные инструкции
    return render_template('deposit.html', wallet_address=user.wallet_address)

@staking_bp.route('/confirm', methods=['POST'])
def confirm_staking():
    """
    Фронтенд (после успешной транзакции) отправляет txHash сюда.
    Мы проверяем txHash через confirm_staking_tx(...)
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

@staking_bp.route('/api/get_balances', methods=['GET'])
def get_balances():
    """
    Возвращает балансы ETH, WETH, UJO для текущего пользователя.
    """
    if 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /staking/api/get_balances.")
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.wallet_address:
        logger.warning(f"Пользователь ID {user_id} не найден или не имеет кошелька.")
        return jsonify({"error": "User not found or wallet not set."}), 404

    try:
        wallet_address = user.wallet_address

        # Получение баланса ETH
        eth_balance = Web3.from_wei(web3.eth.get_balance(wallet_address), 'ether')

        # Получение баланса WETH
        weth_balance = get_token_balance(wallet_address, weth_contract)

        # Получение баланса UJO
        ujo_balance = get_token_balance(wallet_address, ujo_contract)

        return jsonify({
            "balances": {
                "eth": float(eth_balance),
                "weth": float(weth_balance),
                "ujo": float(ujo_balance)
            }
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при получении балансов для пользователя ID {user_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/exchange_weth_to_ujo', methods=['POST'])
def exchange_weth_to_ujo_route():
    """
    Обменивает WETH на UJO для пользователя.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/exchange_weth_to_ujo.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.wallet_address:
            logger.warning(f"Пользователь ID {user_id} не найден или не имеет кошелька.")
            return jsonify({"error": "User not found or wallet not set."}), 404

        data = request.get_json() or {}
        amount_weth = data.get("amount_weth")
        if amount_weth is None:
            logger.warning("amount_weth не предоставлен в запросе.")
            return jsonify({"error": "No amount_weth provided."}), 400

        try:
            amount_weth = float(amount_weth)
            if amount_weth <= 0:
                raise ValueError
        except ValueError:
            logger.warning(f"Некорректное значение amount_weth: {amount_weth}")
            return jsonify({"error": "Invalid amount_weth."}), 400

        logger.info(f"Пользователь ID {user_id} хочет обменять {amount_weth} WETH на UJO.")

        # Выполнение обмена
        success = exchange_weth_to_ujo(user.wallet_address, amount_weth)
        if success:
            ujo_received = amount_weth * 10  # Пример: 1 WETH = 10 UJO
            return jsonify({"status": "success", "ujo_received": ujo_received}), 200
        else:
            return jsonify({"error": "Exchange failed."}), 400

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при обмене WETH на UJO: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

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

        # Отправка стейка пользователю
        success = send_token_reward(user.wallet_address, unstake_after_fee)
        if not success:
            logger.error(f"Отправка стейка не удалась для пользователя ID {user_id}.")
            db.session.rollback()
            return jsonify({"error": "send_token_reward failed"}), 400

        # Отправка 1% fee на проектный кошелек
        project_wallet = PROJECT_WALLET_ADDRESS  # Используем импортированную переменную
        if not project_wallet:
            logger.error("PROJECT_WALLET_ADDRESS не задан.")
            db.session.rollback()
            return jsonify({"error": "Internal server error."}), 500

        fee_success = send_token_reward(project_wallet, fee)
        if not fee_success:
            logger.error(f"Отправка сбора {fee:.4f} UJO на проектный кошелек не удалась.")
            db.session.rollback()
            return jsonify({"error": "Failed to send fee to project wallet."}), 400

        # Если всё ок — возможно отключим premium, если все стейки обнулены.
        # Проверим, остались ли у него стейки
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
