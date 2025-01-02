# routes_staking.py

import logging
import traceback
from datetime import datetime, timedelta
import secrets

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
    PROJECT_WALLET_ADDRESS,
    get_balances,
    generate_unique_wallet_address,
    generate_unique_private_key,
    send_token_reward,

    # Добавлено:
    get_0x_quote,
    approve_0x,
    execute_0x_swap
)
from best_setup_voting import send_token_reward as voting_send_token_reward  # если нужно отличать

logger = logging.getLogger(__name__)

staking_bp = Blueprint('staking_bp', __name__)

@staking_bp.route('/generate_unique_wallet', methods=['POST'])
def generate_unique_wallet_route():
    """
    Генерирует уникальный кошелёк для пользователя.
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("CSRF-токен отсутствует.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found."}), 404

        if user.unique_wallet_address:
            return jsonify({"error": "Unique wallet already exists.", "unique_wallet_address": user.unique_wallet_address}), 400

        # Генерация
        unique_wallet_address = generate_unique_wallet_address()
        unique_private_key = generate_unique_private_key()

        user.unique_wallet_address = unique_wallet_address
        user.unique_private_key = unique_private_key
        db.session.commit()

        logger.info(f"Сгенерирован кошелёк {unique_wallet_address} для пользователя {user_id}")
        return jsonify({"status": "success", "unique_wallet_address": unique_wallet_address}), 200
    except CSRFError as e:
        logger.error(f"CSRF ошибка: {e}")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/generate_unique_wallet_page', methods=['GET'])
def generate_unique_wallet_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите.', 'warning')
        return redirect(url_for('login'))
    return render_template('generate_unique_wallet.html')

@staking_bp.route('/deposit', methods=['GET'])
def deposit_page():
    if 'user_id' not in session:
        flash('Войдите.', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Пользователь не найден.', 'danger')
        return redirect(url_for('login'))

    if not user.unique_wallet_address:
        flash('Сначала сгенерируйте кошелёк для депозита.', 'warning')
        return redirect(url_for('staking_bp.generate_unique_wallet_page'))

    return render_template('deposit.html', unique_wallet_address=user.unique_wallet_address)

@staking_bp.route('/subscription', methods=['GET'])
def subscription_page():
    if 'user_id' not in session:
        flash('Войдите.', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Нет пользователя.', 'danger')
        return redirect(url_for('login'))

    if not user.unique_wallet_address:
        flash('Сначала сгенерируйте кошелёк для стейкинга.', 'warning')
        return redirect(url_for('staking_bp.generate_unique_wallet_page'))

    return render_template('subscription.html', user=user)

@staking_bp.route('/confirm', methods=['POST'])
def confirm_staking():
    """
    Подтверждаем транзакцию >=25$, после чего user получает assistant_premium
    """
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

    except CSRFError as e:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка confirm_staking: {e}")
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/get_user_stakes', methods=['GET'])
def get_user_stakes():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    try:
        stakes = UserStaking.query.filter_by(user_id=user_id).all()
        out = []
        for s in stakes:
            out.append({
                'tx_hash': s.tx_hash,
                'staked_amount': s.staked_amount,
                'staked_usd': s.staked_usd,
                'pending_rewards': s.pending_rewards,
                'unlocked_at': int(s.unlocked_at.timestamp() * 1000)
            })
        return jsonify({'stakes': out}), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/get_balances', methods=['GET'])
def get_balances_route():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.unique_wallet_address:
        return jsonify({"error": "User not found or unique wallet set."}), 404

    b = get_balances(user)
    if "error" in b:
        return jsonify({"error": b["error"]}), 500
    return jsonify(b), 200

@staking_bp.route('/api/exchange_tokens', methods=['POST'])
def exchange_tokens():
    """
    Пример обработки «обмена»:
      - Если from_token=WETH и to_token=UJO => exchange_weth_to_ujo() (старый демо-кейс)
      - Иначе используем 0x (get_0x_quote / approve_0x / execute_0x_swap).
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address:
            return jsonify({"error": "User not found or unique wallet set."}), 404

        data = request.get_json() or {}
        from_token = data.get("from_token")
        to_token = data.get("to_token")
        from_amount = data.get("from_amount")

        if not from_token or not to_token or from_amount is None:
            return jsonify({"error": "Insufficient data for exchange."}), 400

        # Проверяем from_amount
        try:
            from_amount = float(from_amount)
            if from_amount <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid from_amount."}), 400

        logger.info(f"[exchange_tokens] User {user_id}: {from_token} -> {to_token}, amount={from_amount}")

        # --- 1) Старый демо-кейс: WETH -> UJO (exchange_weth_to_ujo) ---
        if from_token.upper() == "WETH" and to_token.upper() == "UJO":
            ok = exchange_weth_to_ujo(user.unique_wallet_address, from_amount)
            if ok:
                # Для демо: считаем 1 WETH = 10 UJO
                ujo_received = from_amount * 10
                return jsonify({"status": "success", "ujo_received": ujo_received}), 200
            else:
                return jsonify({"error": "Exchange failed."}), 400

        # --- 2) Настоящий обмен через 0x Swap API ---
        else:
            # Преобразуем from_token, to_token в адреса контрактов (или 0xEEE... для ETH):
            if from_token.upper() == "ETH":
                sell_token_0x = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
                from_decimals = 18
            elif from_token.upper() == "WETH":
                sell_token_0x = weth_contract.address  # или WETH_CONTRACT_ADDRESS
                from_decimals = 18  # можно уточнить реально из контракта
            elif from_token.upper() == "UJO":
                sell_token_0x = ujo_contract.address
                from_decimals = 18
            else:
                return jsonify({"error": f"Unsupported from_token={from_token}"}), 400

            if to_token.upper() == "ETH":
                buy_token_0x = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
                to_decimals = 18
            elif to_token.upper() == "WETH":
                buy_token_0x = weth_contract.address
                to_decimals = 18
            elif to_token.upper() == "UJO":
                buy_token_0x = ujo_contract.address
                to_decimals = 18
            else:
                return jsonify({"error": f"Unsupported to_token={to_token}"}), 400

            # Конвертируем float -> wei
            from_amount_wei = int(from_amount * (10**from_decimals))
            taker_address = user.unique_wallet_address
            user_pk = user.unique_private_key

            # 2.1) Получаем котировку 0x
            quote = get_0x_quote(
                sell_token=sell_token_0x,
                buy_token=buy_token_0x,
                sell_amount_wei=from_amount_wei,
                taker_address=taker_address
            )
            if not quote or "to" not in quote or "data" not in quote:
                return jsonify({"error": "Failed to get 0x quote."}), 400

            # 2.2) Если from_token != ETH => нужно проверить allowance и при необходимости approve
            if sell_token_0x.lower() != "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
                allowance_target = quote.get("allowanceTarget")  # 0x указывает, кто будет забирать токены
                if allowance_target:
                    # Проверяем allowance реальный
                    erc20_contract = web3.eth.contract(address=web3.toChecksumAddress(sell_token_0x), abi=token_contract.abi)
                    current_allowance = erc20_contract.functions.allowance(
                        web3.toChecksumAddress(taker_address),
                        web3.toChecksumAddress(allowance_target)
                    ).call()

                    if current_allowance < from_amount_wei:
                        # Делаем approve
                        logger.info(f"Current allowance={current_allowance}, need={from_amount_wei}, calling approve_0x")
                        ok_approve = approve_0x(
                            token_address=sell_token_0x,
                            spender=allowance_target,
                            amount_wei=from_amount_wei,  # или можно 2**256 - 1 для unlimited
                            private_key=user_pk
                        )
                        if not ok_approve:
                            return jsonify({"error": "approve_0x failed"}), 400
                else:
                    logger.warning("quote без allowanceTarget, возможно sellToken=ETH?")

            # 2.3) Выполняем swap
            swap_ok = execute_0x_swap(quote, user_pk)
            if not swap_ok:
                return jsonify({"error": "0x swap failed"}), 400

            # 2.4) Узнаём, сколько купили
            buy_amount_float = 0.0
            if "buyAmount" in quote:
                buy_amount_float = float(quote["buyAmount"]) / (10**to_decimals)

            # Готово
            return jsonify({
                "status": "success",
                "ujo_received": buy_amount_float  # если to_token=UJO
            }), 200

    except CSRFError as e:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"exchange_tokens error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/claim_staking_rewards', methods=['POST'])
def claim_staking_rewards_route():
    """
    Клейм pending_rewards, раз в 7 дней
    """
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

        stakings = UserStaking.query.filter_by(user_id=user_id).all()
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

        if totalRewards <= 0.0:
            return jsonify({"error": "Пока нечего клеймить"}), 400

        if not user.unique_wallet_address:
            return jsonify({"error": "No unique wallet"}), 400

        ok = send_token_reward(user.unique_wallet_address, totalRewards)
        if ok:
            db.session.commit()
            return jsonify({"message": f"Claimed {totalRewards:.4f} UJO"}), 200
        else:
            db.session.rollback()
            return jsonify({"error": "Ошибка транзакции"}), 400
    except CSRFError as e:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/unstake', methods=['POST'])
def unstake_staking_route():
    """
    Вывод стейка, если прошёл срок (30д). 1% fee
    """
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address:
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
            return jsonify({"error": "Нет доступных стейков"}), 400

        unstake_after_fee = total_unstake * 0.99
        fee = total_unstake * 0.01
        logger.info(f"Unstake {total_unstake:.4f} UJO -> fee={fee:.4f}")

        ok = send_token_reward(user.unique_wallet_address, unstake_after_fee)
        if not ok:
            db.session.rollback()
            return jsonify({"error": "send_token_reward failed"}), 400

        project_wallet = PROJECT_WALLET_ADDRESS
        if not project_wallet:
            db.session.rollback()
            return jsonify({"error": "PROJECT_WALLET_ADDRESS not set"}), 500

        fee_ok = send_token_reward(project_wallet, fee)
        if not fee_ok:
            db.session.rollback()
            return jsonify({"error": "Failed to send fee"}), 400

        # Если нет активных стейков
        remaining = UserStaking.query.filter(UserStaking.user_id==user_id, UserStaking.staked_amount>0).count()
        if remaining == 0:
            user.assistant_premium = False

        db.session.commit()
        return jsonify({"message": f"Unstaked {total_unstake:.4f}, got {unstake_after_fee:.4f} after 1% fee"}), 200
    except CSRFError as e:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/stake_tokens', methods=['POST'])
def stake_tokens():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address:
            return jsonify({"error": "User not found or unique wallet set."}), 404

        data = request.get_json() or {}
        amount_usd = data.get("amount_usd")
        if amount_usd is None:
            return jsonify({"error": "No amount_usd provided."}), 400

        try:
            amount_usd = float(amount_usd)
            if amount_usd <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid amount_usd."}), 400

        price_usd = get_token_price_in_usd()
        if not price_usd:
            return jsonify({"error": "Failed to get UJO price."}), 400

        amount_ujo = amount_usd / price_usd

        ok = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=amount_ujo,
            from_address=user.unique_wallet_address,
            private_key=user.unique_private_key
        )
        if not ok:
            return jsonify({"error": "Staking failed."}), 400

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

        return jsonify({"status": "success", "staked_amount": amount_ujo, "staked_usd": amount_usd}), 200
    except CSRFError as e:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/withdraw_funds', methods=['POST'])
def withdraw_funds():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or not user.unique_wallet_address or not user.wallet_address:
            return jsonify({"error": "User not found or wallet address not set."}), 400

        ujo_balance = get_token_balance(user.unique_wallet_address, ujo_contract)
        if ujo_balance <= 0.0:
            return jsonify({"error": "No UJO tokens to withdraw."}), 400

        ok = send_token_reward(
            to_address=user.wallet_address,
            amount=ujo_balance,
            from_address=user.unique_wallet_address,
            private_key=user.unique_private_key
        )
        if ok:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Failed to send tokens."}), 400

    except CSRFError as e:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": "Internal server error."}), 500
