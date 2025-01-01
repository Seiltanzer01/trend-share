# routes_staking.py

import logging
import traceback
from datetime import datetime, timedelta
import secrets
import string

from flask import Blueprint, request, jsonify, session, render_template, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from models import db, User, UserStaking
from staking_logic import (
    confirm_staking_tx,
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

# Функции генерации уникального адреса кошелька и приватного ключа

def generate_unique_wallet_address():
    """
    Генерирует уникальный адрес кошелька в формате checksum.
    """
    while True:
        address = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(40))
        # Преобразование в checksum адрес
        checksum_address = Web3.to_checksum_address(address)
        # Проверка уникальности адреса в базе данных
        if not User.query.filter_by(unique_wallet_address=checksum_address).first():
            return checksum_address

def generate_unique_private_key():
    """
    Генерирует уникальный приватный ключ.
    """
    # Генерация случайного 32-байтового ключа и преобразование в шестнадцатеричную строку
    private_key = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(64))
    return private_key

@staking_bp.route('/generate_unique_wallet', methods=['POST'])
def generate_unique_wallet_route():
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
            logger.warning("Неавторизованный доступ к /staking/generate_unique_wallet.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Пользователь с ID {user_id} не найден.")
            return jsonify({"error": "User not found."}), 404

        if user.unique_wallet_address:
            logger.info(f"Пользователь ID {user_id} уже имеет уникальный кошелек: {user.unique_wallet_address}")
            return jsonify({"error": "Unique wallet already exists.", "unique_wallet_address": user.unique_wallet_address}), 400

        # Генерация уникального кошелька
        unique_wallet_address = generate_unique_wallet_address()
        unique_private_key = generate_unique_private_key()

        # Сохранение кошелька в базе данных
        user.unique_wallet_address = unique_wallet_address
        user.unique_private_key = unique_private_key
        db.session.commit()

        logger.info(f"Сгенерирован уникальный кошелёк для пользователя ID {user_id}: {unique_wallet_address}")

        return jsonify({"status": "success", "unique_wallet_address": unique_wallet_address}), 200

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при генерации уникального кошелька: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/deposit', methods=['GET'])
def deposit_page():
    """
    Страница для депозита токенов. Показывает уникальный адрес кошелька и инструкции.
    """
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для депозита.', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Пользователь не найден.', 'danger')
        return redirect(url_for('login'))

    if not user.unique_wallet_address:
        flash('Сначала сгенерируйте уникальный кошелёк для депозита.', 'warning')
        return redirect(url_for('staking_bp.generate_unique_wallet_page'))

    # Здесь можно добавить дополнительные инструкции
    return render_template('deposit.html', unique_wallet_address=user.unique_wallet_address)

@staking_bp.route('/generate_unique_wallet_page', methods=['GET'])
def generate_unique_wallet_page():
    """
    Страница для генерации уникального кошелька.
    """
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для генерации кошелька.', 'warning')
        return redirect(url_for('login'))

    return render_template('generate_unique_wallet.html')

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

        # Используем уникальный кошелёк для подтверждения стейкинга
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

@staking_bp.route('/api/get_user_stakes', methods=['GET'])
def get_user_stakes():
    """
    Возвращает стейкинговые данные пользователя.
    """
    if 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /staking/api/get_user_stakes.")
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        logger.warning(f"Пользователь ID {user_id} не найден.")
        return jsonify({"error": "User not found."}), 404

    try:
        stakes = UserStaking.query.filter_by(user_id=user_id).all()
        stakes_data = []
        for stake in stakes:
            stakes_data.append({
                'tx_hash': stake.tx_hash,
                'staked_amount': stake.staked_amount,
                'staked_usd': stake.staked_usd,
                'pending_rewards': stake.pending_rewards,
                'unlocked_at': int(stake.unlocked_at.timestamp() * 1000)  # Преобразуем в миллисекунды для JS
            })

        return jsonify({'stakes': stakes_data}), 200

    except Exception as e:
        logger.error(f"Ошибка при получении стейкингов для пользователя ID {user_id}: {e}")
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
    if not user or not user.unique_wallet_address:
        logger.warning(f"Пользователь ID {user_id} не найден или не имеет уникального кошелька.")
        return jsonify({"error": "User not found or unique wallet set."}), 404

    try:
        unique_wallet_address = Web3.to_checksum_address(user.unique_wallet_address)

        # Получение баланса ETH
        eth_balance = Web3.from_wei(web3.eth.get_balance(unique_wallet_address), 'ether')

        # Получение баланса WETH
        weth_balance = get_token_balance(unique_wallet_address, weth_contract)

        # Получение баланса UJO
        ujo_balance = get_token_balance(unique_wallet_address, ujo_contract)

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

@staking_bp.route('/api/exchange_tokens', methods=['POST'])
def exchange_tokens():
    """
    Обменивает токены между пользователем.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/api/exchange_tokens.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address:
            logger.warning(f"Пользователь ID {user_id} не найден или не имеет уникального кошелька.")
            return jsonify({"error": "User not found or unique wallet set."}), 404

        data = request.get_json() or {}
        from_token = data.get("from_token")
        to_token = data.get("to_token")
        from_amount = data.get("from_amount")

        if not from_token or not to_token or from_amount is None:
            logger.warning("Недостаточно данных для обмена.")
            return jsonify({"error": "Insufficient data for exchange."}), 400

        try:
            from_amount = float(from_amount)
            if from_amount <= 0:
                raise ValueError
        except ValueError:
            logger.warning(f"Некорректное значение from_amount: {from_amount}")
            return jsonify({"error": "Invalid from_amount."}), 400

        logger.info(f"Пользователь ID {user_id} хочет обменять {from_amount} {from_token} на {to_token}.")

        # Выполнение обмена
        # Здесь предполагается, что функция exchange_weth_to_ujo обрабатывает обмен между любыми токенами
        # Если нет, необходимо реализовать соответствующую логику

        # Для примера, будем считать, что обмен возможен только между WETH и UJO
        if from_token == "WETH" and to_token == "UJO":
            success = exchange_weth_to_ujo(user.unique_wallet_address, from_amount)
            if success:
                # Пример расчёта полученных UJO (замените на реальную логику)
                ujo_received = from_amount * 10  # Пример: 1 WETH = 10 UJO
                return jsonify({"status": "success", "ujo_received": ujo_received}), 200
            else:
                return jsonify({"error": "Exchange failed."}), 400
        else:
            logger.warning(f"Обмен между {from_token} и {to_token} не поддерживается.")
            return jsonify({"error": "Exchange between these tokens is not supported."}), 400

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при обмене токенов: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/claim_staking_rewards', methods=['POST'])
def claim_staking_rewards_route():
    """
    Пользователь может клеймить награды раз в неделю.
    При клейме отправляем pending_rewards.
    После отправки обнуляем pending_rewards и обновляем last_claim_at.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/api/claim_staking_rewards.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Пользователь ID {user_id} не найден.")
            return jsonify({"error": "User not found."}), 404

        stakings = UserStaking.query.filter_by(user_id=user_id).all()
        if not stakings:
            return jsonify({"error": "У вас нет стейкинга."}), 400

        now = datetime.utcnow()
        totalRewards = 0.0
        for s in stakings:
            if s.staked_amount > 0:
                # Проверка, прошло ли 7 дней с последнего клейма
                delta = now - s.last_claim_at
                if delta >= timedelta(days=7):
                    totalRewards += s.pending_rewards
                    s.pending_rewards = 0.0
                    s.last_claim_at = now

        if totalRewards <= 0.0:
            return jsonify({"error": "Пока нечего клеймить, либо не прошла неделя."}), 400

        # Отправка наград
        if not user.unique_wallet_address:
            return jsonify({"error": "No unique wallet address."}), 400

        success = send_token_reward(user.unique_wallet_address, totalRewards)
        if success:
            db.session.commit()
            return jsonify({"message": f"Claimed {totalRewards:.4f} UJO успешно отправлен на {user.unique_wallet_address}."}), 200
        else:
            db.session.rollback()
            return jsonify({"error": "Ошибка транзакции."}), 400

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при клейме наград: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/unstake', methods=['POST'])
def unstake_staking_route():
    """
    Выводит стейк, если прошёл срок (30 дней).
    При выводе удерживаем 1% fee.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/api/unstake.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address:
            logger.warning(f"Пользователь ID {user_id} не найден или не имеет уникального кошелька.")
            return jsonify({"error": "User not found or unique wallet set."}), 400

        stakings = UserStaking.query.filter_by(user_id=user_id).all()
        total_unstake = 0.0
        now = datetime.utcnow()
        for s in stakings:
            if s.staked_amount > 0 and s.unlocked_at <= now:
                total_unstake += s.staked_amount
                s.staked_amount = 0.0
                s.staked_usd = 0.0
                s.pending_rewards = 0.0

        if total_unstake <= 0.0:
            logger.info(f"Пользователь ID {user_id} не имеет доступных стейков для вывода.")
            return jsonify({"error": "Нет доступных стейков для вывода (либо ещё не прошло 30 дней)."}), 400

        # Удержим 1%
        unstake_after_fee = total_unstake * 0.99
        fee = total_unstake * 0.01

        logger.info(f"Пользователь ID {user_id} выводит {total_unstake:.4f} UJO (сбор 1%: {fee:.4f} UJO).")

        # Отправка стейка пользователю
        success = send_token_reward(user.unique_wallet_address, unstake_after_fee)
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

        # Проверяем, остались ли активные стейки
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

@staking_bp.route('/api/stake_tokens', methods=['POST'])
def stake_tokens():
    """
    Стейкинг токенов. Отправляет UJO с уникального кошелька на кошелек проекта.
    """
    try:
        # Извлечение CSRF-токена из заголовков
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует в заголовках.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            logger.warning("Неавторизованный доступ к /staking/api/stake_tokens.")
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address:
            logger.warning(f"Пользователь ID {user_id} не найден или не имеет уникального кошелька.")
            return jsonify({"error": "User not found or unique wallet set."}), 404

        data = request.get_json() or {}
        amount_usd = data.get("amount_usd")
        if amount_usd is None:
            logger.warning("amount_usd не предоставлен в запросе.")
            return jsonify({"error": "No amount_usd provided."}), 400

        try:
            amount_usd = float(amount_usd)
            if amount_usd <= 0:
                raise ValueError
        except ValueError:
            logger.warning(f"Некорректное значение amount_usd: {amount_usd}")
            return jsonify({"error": "Invalid amount_usd."}), 400

        # Получение текущей цены UJO
        price_usd = get_token_price_in_usd('UJO')  # Предполагается, что есть такая функция
        if not price_usd:
            logger.error("Не удалось получить цену токена UJO.")
            return jsonify({"error": "Failed to get UJO price."}), 400

        amount_ujo = amount_usd / price_usd

        # Отправка UJO с уникального кошелька на кошелек проекта
        success = send_token_reward(PROJECT_WALLET_ADDRESS, amount_ujo, from_address=user.unique_wallet_address)
        if not success:
            logger.error(f"Стейкинг не удался для пользователя ID {user_id}.")
            return jsonify({"error": "Staking failed."}), 400

        # Добавление записи стейкинга в базу данных
        new_stake = UserStaking(
            user_id=user_id,
            tx_hash=f"staking_{datetime.utcnow().timestamp()}_{secrets.token_hex(8)}",
            staked_amount=amount_ujo,
            staked_usd=amount_usd,
            pending_rewards=0.0,
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow() + timedelta(days=30),
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_stake)
        db.session.commit()

        logger.info(f"Пользователь ID {user_id} застейкал {amount_ujo:.4f} UJO (~{amount_usd}$).")

        return jsonify({"status": "success", "staked_amount": amount_ujo, "staked_usd": amount_usd}), 200

    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка при стейкинге токенов: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500
