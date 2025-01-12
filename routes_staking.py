# routes_staking.py

import logging
import traceback
import os
from datetime import datetime, timedelta
import secrets
import string

from flask import Blueprint, request, jsonify, session, render_template, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from web3 import Web3
from models import db, User, UserStaking
from staking_logic import (
    confirm_staking_tx,
    get_token_balance,
    get_token_price_in_usd,
    web3,
    token_contract,
    weth_contract,
    ujo_contract,
    UJO_CONTRACT_ADDRESS,
    TOKEN_CONTRACT_ADDRESS,
    WETH_CONTRACT_ADDRESS,
    PROJECT_WALLET_ADDRESS,
    ERC20_ABI,
    get_balances,
    generate_unique_wallet,
    send_token_reward,
    swap_tokens_via_1inch,
    deposit_eth_to_weth,
    verify_private_key,
    send_eth_from_user,
)
from best_setup_voting import send_token_reward as voting_send_token_reward  # Для совместимости

logger = logging.getLogger(__name__)

staking_bp = Blueprint('staking_bp', __name__)


@staking_bp.route('/generate_unique_wallet', methods=['POST'])
def generate_unique_wallet_route():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found."}), 404

        if user.unique_wallet_address:
            return jsonify({
                "error": "Unique wallet already exists.",
                "unique_wallet_address": user.unique_wallet_address
            }), 400

        unique_wallet_address, unique_private_key = generate_unique_wallet()

        # Проверка соответствия приватного ключа и адреса
        temp_user = User(
            unique_wallet_address=unique_wallet_address,
            unique_private_key=unique_private_key
        )
        if not verify_private_key(temp_user):
            return jsonify({"error": "Generated private key does not match the wallet address."}), 500

        user.unique_wallet_address = unique_wallet_address
        user.unique_private_key = unique_private_key
        db.session.commit()

        logger.info(f"Уникальный кошелёк {unique_wallet_address} для user_id={user_id}")
        return jsonify({"status": "success", "unique_wallet_address": unique_wallet_address}), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/generate_unique_wallet_page', methods=['GET'])
def generate_unique_wallet_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите.', 'warning')
        return redirect(url_for('login'))
    # Вместо отрисовки несуществующего шаблона — перенаправляем на страницу депозита.
    return redirect(url_for('staking_bp.deposit_page'))


@staking_bp.route('/deposit', methods=['GET'])
def deposit_page():
    if 'user_id' not in session:
        flash('Войдите для депозита.', 'warning')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Нет пользователя', 'danger')
        return redirect(url_for('login'))

    if not user.unique_wallet_address:
        flash('Сначала сгенерируйте кошелёк.', 'warning')
        return redirect(url_for('staking_bp.generate_unique_wallet_page'))

    return render_template('deposit.html', unique_wallet_address=user.unique_wallet_address)


@staking_bp.route('/subscription', methods=['GET'])
def subscription_page():
    if 'user_id' not in session:
        flash('Войдите.', 'warning')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Нет пользователя.', 'danger')
        return redirect(url_for('login'))

    if not user.unique_wallet_address:
        flash('Сгенерируйте кошелёк.', 'warning')
        return redirect(url_for('staking_bp.generate_unique_wallet_page'))

    return render_template('subscription.html', user=user)


@staking_bp.route('/confirm', methods=['POST'])
def confirm_staking():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing"}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({"error": "User not found"}), 404

        data = request.get_json() or {}
        tx_hash = data.get("txHash")
        if not tx_hash:
            return jsonify({"error": "No txHash provided"}), 400

        ok = confirm_staking_tx(user, tx_hash)
        if ok:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Staking confirm failed"}), 400

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка confirm_staking: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/api/get_user_stakes', methods=['GET'])
def get_user_stakes():
    """
    Возвращаем стейки, но показываем только те, у которых staked_amount > 0.
    Таким образом, если пользователь сделал unstake и staked_amount=0,
    они не будут отображаться.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        stakings = UserStaking.query.filter_by(user_id=user.id).all()

        stakes_data = []
        for s in stakings:
            if s.staked_amount > 0:  # Показываем только активные стейки
                stakes_data.append({
                    'tx_hash': s.tx_hash,
                    'staked_amount': float(s.staked_amount),
                    'staked_usd': float(s.staked_usd),
                    'pending_rewards': float(s.pending_rewards),
                    'unlocked_at': int(s.unlocked_at.timestamp() * 1000)
                })
        return jsonify({"stakes": stakes_data}), 200
    except Exception as e:
        logger.error(f"Ошибка get_user_stakes: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/api/get_balances', methods=['GET'])
def get_balances_route():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.get(session['user_id'])
    if not user or not user.unique_wallet_address:
        return jsonify({"error": "User not found or unique wallet not set."}), 404

    result = get_balances(user)
    if "error" in result:
        return jsonify({"error": result["error"]}), 500
    return jsonify(result), 200


@staking_bp.route('/api/exchange_tokens', methods=['POST'])
def exchange_tokens():
    """
    Рабочий код обмена через 1inch
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address:
            return jsonify({"error": "User not found or unique wallet not set."}), 404

        data = request.get_json() or {}
        from_token = data.get("from_token")
        to_token = data.get("to_token")
        from_amount = data.get("from_amount")

        if not from_token or not to_token or from_amount is None:
            return jsonify({"error": "Недостаточно данных для обмена."}), 400

        try:
            from_amount = float(from_amount)
            if from_amount <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Некорректное значение from_amount."}), 400

        # Определяем, ETH ли это
        def get_token_address(symbol: str) -> str:
            symbol_upper = symbol.upper()
            if symbol_upper == "ETH":
                return "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
            elif symbol_upper == "WETH":
                return WETH_CONTRACT_ADDRESS
            elif symbol_upper == "UJO":
                return UJO_CONTRACT_ADDRESS
            else:
                return symbol

        sell_token = get_token_address(from_token)
        buy_token = get_token_address(to_token)
        logger.info(f"Обмен: {from_amount} {from_token} ({sell_token}) -> {to_token} ({buy_token})")

        # Проверка баланса пользователя
        if from_token.upper() == "ETH":
            user_eth_balance = Web3.from_wei(
                web3.eth.get_balance(user.unique_wallet_address),
                'ether'
            )
            logger.info(f"Баланс пользователя ETH: {user_eth_balance}")
            if user_eth_balance < from_amount:
                return jsonify({"error": "Недостаточно ETH для обмена."}), 400
        else:
            # ERC20
            if sell_token.lower() == TOKEN_CONTRACT_ADDRESS.lower():
                sell_contract = token_contract
            elif sell_token.lower() == WETH_CONTRACT_ADDRESS.lower():
                sell_contract = weth_contract
            elif sell_token.lower() == UJO_CONTRACT_ADDRESS.lower():
                sell_contract = ujo_contract
            else:
                sell_contract = web3.eth.contract(
                    address=Web3.to_checksum_address(sell_token),
                    abi=ERC20_ABI
                )
            user_balance = get_token_balance(user.unique_wallet_address, sell_contract)
            logger.info(f"Баланс пользователя {from_token}: {user_balance}")
            if user_balance < from_amount:
                return jsonify({"error": f"Недостаточно {from_token} для обмена."}), 400

        # Обмен через 1inch
        swap_ok = swap_tokens_via_1inch(
            user.unique_private_key,
            sell_token,
            buy_token,
            from_amount
        )
        if not swap_ok:
            logger.error("Ошибка выполнения обмена через 1inch.")
            return jsonify({"error": "Ошибка выполнения обмена через 1inch."}), 400

        # Обновим балансы
        result = get_balances(user)
        if "error" in result:
            return jsonify({"error": result["error"]}), 500

        logger.info(f"Успешный обмен: {from_token} -> {to_token}, сумма: {from_amount}")
        return jsonify({
            "status": "success",
            "balances": result["balances"]
        }), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка exchange_tokens: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/api/claim_staking_rewards', methods=['POST'])
def claim_staking_rewards_route():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({"error": "User not found."}), 404

        stakings = UserStaking.query.filter_by(user_id=user.id).all()
        if not stakings:
            return jsonify({"error": "У вас нет стейкинга."}), 400

        now = datetime.utcnow()
        totalRewards = 0.0
        for s in stakings:
            if s.staked_amount > 0:
                delta = now - s.last_claim_at
                if delta >= timedelta(days=7):
                    totalRewards += s.pending_rewards
                    s.pending_rewards = 0.0
                    s.last_claim_at = now

        if totalRewards <= 0:
            return jsonify({"error": "Пока нечего клеймить"}), 400

        if not user.unique_wallet_address:
            return jsonify({"error": "No unique wallet address"}), 400

        ok = send_token_reward(
            to_address=user.unique_wallet_address,
            amount=totalRewards,
            private_key=os.environ.get("PRIVATE_KEY")
        )
        if not ok:
            db.session.rollback()
            return jsonify({"error": "Ошибка транзакции"}), 400

        db.session.commit()
        return jsonify({"message": f"Claimed {totalRewards:.4f} UJO"}), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error("claim_staking_rewards_route exception", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/api/unstake', methods=['POST'])
def unstake_staking_route():
    """
    Unstake c 1% fee.
    Если пользователь unstake'ит всё (staked_amount=...), тогда
    staked_amount=0 -> запись перестаёт отображаться в /api/get_user_stakes
    и пользователь может заново сделать stake.
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address or not user.wallet_address:
            return jsonify({"error": "User not found or wallet address not set."}), 400

        stakings = UserStaking.query.filter_by(user_id=user.id).all()
        total_unstake = 0.0
        now = datetime.utcnow()

        for s in stakings:
            if s.staked_amount > 0 and s.unlocked_at <= now:
                total_unstake += s.staked_amount
                s.staked_usd = 0.0
                s.staked_amount = 0.0
                s.pending_rewards = 0.0

        if total_unstake <= 0:
            return jsonify({"error": "Нет доступных стейкингов для unstake."}), 400

        fee = total_unstake * 0.01
        withdraw_amount = total_unstake - fee

        success = send_token_reward(
            to_address=user.unique_wallet_address,
            amount=withdraw_amount,
            private_key=os.environ.get("PRIVATE_KEY"),
            token_contract_instance=token_contract
        )
        if not success:
            db.session.rollback()
            return jsonify({"error": "Ошибка при отправке UJO на кошелек пользователя."}), 400

        fee_success = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=fee,
            private_key=os.environ.get("PRIVATE_KEY"),
            token_contract_instance=token_contract
        )
        if not fee_success:
            db.session.rollback()
            return jsonify({"error": "Ошибка при отправке комиссии."}), 400

        # Если у пользователя больше не осталось стейков >0, снимаем premium
        active_count = UserStaking.query.filter(
            UserStaking.user_id == user.id,
            UserStaking.staked_amount > 0
        ).count()
        if active_count == 0:
            user.assistant_premium = False

        db.session.commit()
        return jsonify({
            "message": f"Unstaked {total_unstake:.4f} UJO (fee: 1%, you got {withdraw_amount:.4f} UJO)."
        }), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"unstake_staking error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


###################################################################
# ОБРАТИТЕ ВНИМАНИЕ: мы делаем ТЕСТ: 0.5$ => (0.2 + 0.3)
###################################################################
@staking_bp.route('/api/stake_tokens', methods=['POST'])
def stake_tokens_route():
    """
    (ТЕСТОВЫЙ вариант)
    total_usd=0.5 => fee=0.2, stake=0.3

    Теперь проверяем, есть ли у пользователя стейки >0. 
    Если нет, разрешаем стейк. Если хотя бы один > 0, запрещаем.
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address:
            return jsonify({"error": "User not found or unique wallet."}), 404

        # Есть ли у пользователя стейк staked_amount>0?
        active_stake = UserStaking.query.filter(
            UserStaking.user_id == user.id,
            UserStaking.staked_amount > 0
        ).first()
        if active_stake:
            return jsonify({"error": "У вас уже есть активный стейк. Повторный стейк невозможен."}), 400

        data = request.get_json() or {}
        total_usd = data.get("amount_usd")  # Ожидаем 0.5
        if total_usd is None:
            return jsonify({"error": "No amount_usd provided."}), 400

        try:
            total_usd = float(total_usd)
            if total_usd < 0.5:
                return jsonify({"error": "Сейчас нужно ровно 0.5$ (тест)."}), 400
        except ValueError:
            return jsonify({"error": "Invalid amount_usd."}), 400

        stake_usd = 0.3
        fee_usd = 0.2

        price_usd = get_token_price_in_usd()
        if not price_usd or price_usd <= 0:
            return jsonify({"error": "Failed to get UJO price."}), 400

        fee_ujo = fee_usd / price_usd
        stake_ujo = stake_usd / price_usd
        total_need_ujo = fee_ujo + stake_ujo

        # Проверяем баланс пользователя
        user_balance = get_token_balance(user.unique_wallet_address, token_contract)
        if user_balance < total_need_ujo:
            return jsonify({"error": "Недостаточно UJO на кошельке (тест 0.5$)."}), 400

        # Сначала fee
        ok_fee = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=fee_ujo,
            private_key=user.unique_private_key,
            token_contract_instance=token_contract
        )
        if not ok_fee:
            return jsonify({"error": "Ошибка при отправке 0.2$ (fee)."}), 400

        # Затем stake
        ok_stake = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=stake_ujo,
            private_key=user.unique_private_key,
            token_contract_instance=token_contract
        )
        if not ok_stake:
            return jsonify({"error": "Ошибка при отправке 0.3$ (stake)."}), 400

        # Запись в БД
        new_stake = UserStaking(
            user_id=user.id,
            tx_hash=f"staking_{datetime.utcnow().timestamp()}_{secrets.token_hex(8)}",
            staked_amount=stake_ujo,
            staked_usd=stake_usd,
            pending_rewards=0.0,
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow() + timedelta(minutes=5),
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_stake)
        db.session.commit()

        logger.info(f"[TEST stake] user={user.id}, fee=0.2$, stake=0.3$")
        return jsonify({
            "status": "success",
            "staked_amount": stake_ujo,
            "staked_usd": stake_usd
        }), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"stake_tokens error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/api/withdraw_funds', methods=['POST'])
def withdraw_funds():
    """
    Логика вывода. Пусть любой юзер может установить кошелёк (wallet_address),
    независимо от премиума.
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address or not user.wallet_address:
            return jsonify({"error": "User not found or wallet address not set."}), 400

        data = request.get_json() or {}
        token = data.get("token")
        amount = data.get("amount")

        if not token or amount is None:
            return jsonify({"error": "Недостаточно данных для вывода."}), 400

        token = token.upper()
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Некорректная сумма для вывода."}), 400

        # Получаем балансы
        balances_dict = get_balances(user)
        if "error" in balances_dict:
            return jsonify({"error": balances_dict["error"]}), 500

        available_balance = balances_dict["balances"].get(token.lower(), 0.0)
        if available_balance < amount:
            return jsonify({"error": f"Недостаточно {token} для вывода."}), 400

        if token == "ETH":
            success = send_eth_from_user(
                user_private_key=user.unique_private_key,
                to_address=user.wallet_address,
                amount_eth=amount
            )
        elif token in ["WETH", "UJO"]:
            contract = weth_contract if token == "WETH" else ujo_contract
            success = send_token_reward(
                to_address=user.wallet_address,
                amount=amount,
                from_address=user.unique_wallet_address,
                private_key=user.unique_private_key,
                token_contract_instance=contract
            )
        else:
            return jsonify({"error": "Неподдерживаемая монета для вывода."}), 400

        if success:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Не удалось вывести средства."}), 400

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error("withdraw_funds error", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


@staking_bp.route('/api/get_token_price', methods=['GET'])
def get_token_price_api():
    try:
        price = get_token_price_in_usd()
        if price > 0:
            return jsonify({"price_usd": price}), 200
        else:
            return jsonify({"error": "Price not available"}), 400
    except Exception as e:
        logger.error(f"get_token_price_api error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500
