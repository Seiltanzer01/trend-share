# routes_staking.py

import logging
import traceback
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session, render_template, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from models import db, User, UserStaking
from staking_logic import (
    confirm_staking_tx,
    get_token_balance,
    get_token_price_in_usd,
    web3,
    token_contract,
    weth_contract,
    ujo_contract,
    PROJECT_WALLET_ADDRESS,
    get_balances,
    generate_unique_private_key,
    generate_unique_wallet_address,
    send_token_reward,
    get_0x_quote_v2_permit2,
    execute_0x_swap_v2_permit2,
    deposit_eth_to_weth,
    verify_private_key,
    send_eth_from_project,
)

from best_setup_voting import send_token_reward as voting_send_token_reward

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
            return jsonify({"error": "Unique wallet already exists.",
                            "unique_wallet_address": user.unique_wallet_address}), 400

        unique_private_key = generate_unique_private_key()
        unique_wallet_address = verify_private_key_from_private_key(unique_private_key)
        if not unique_wallet_address:
            return jsonify({"error": "Failed to generate unique wallet."}), 500

        # Присваиваем пользователю адрес и приватный ключ
        user.unique_wallet_address = unique_wallet_address
        user.unique_private_key    = unique_private_key
        db.session.commit()

        logger.info(f"Уникальный кошелёк {unique_wallet_address} для user_id={user_id}")

        # Автоматическое финансирование уникального кошелька
        funding_amount = 0.0025  # Вы можете изменить сумму по необходимости
        funding_ok = send_eth_from_project(
            to_address=unique_wallet_address,
            amount_eth=funding_amount
        )
        if not funding_ok:
            logger.error(f"Не удалось отправить ETH на {unique_wallet_address}")
            return jsonify({"error": "Failed to fund the unique wallet."}), 500

        return jsonify({"status": "success", "unique_wallet_address": unique_wallet_address}), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

def verify_private_key_from_private_key(private_key: str) -> str:
    """
    Генерирует адрес кошелька из приватного ключа.
    """
    try:
        address = get_address_from_private_key(private_key)
        return address
    except:
        return None

@staking_bp.route('/generate_unique_wallet_page', methods=['GET'])
def generate_unique_wallet_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите.', 'warning')
        return redirect(url_for('login'))
    return render_template('generate_unique_wallet.html')

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
        return jsonify({"error": "CSRF token missing or invalid"}), 400
    except Exception as e:
        logger.error(f"Ошибка confirm_staking: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/get_user_stakes', methods=['GET'])
def get_user_stakes():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        stakes = UserStaking.query.filter_by(user_id=user.id).all()
        stakes_data = []
        for s in stakes:
            stakes_data.append({
                'tx_hash':          s.tx_hash,
                'staked_amount':    s.staked_amount,
                'staked_usd':       s.staked_usd,
                'pending_rewards':  s.pending_rewards,
                'unlocked_at':      int(s.unlocked_at.timestamp()*1000)
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
        return jsonify({"error": "User not found or unique wallet set."}), 404

    result = get_balances(user)
    if "error" in result:
        return jsonify({"error": result["error"]}), 500
    return jsonify(result), 200

@staking_bp.route('/api/exchange_tokens', methods=['POST'])
def exchange_tokens():
    """
    Обмен токенов (ETH/WETH/UJO) без ручного approve, т.к. 
    приватный ключ кошелька хранится в нашем бэкенде.

    Если from_token=ETH => сначала делаем deposit_eth_to_weth, 
    чтобы получить WETH, и уже WETH меняем на to_token.
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
            return jsonify({"error": "User not found or unique wallet set."}), 404

        data        = request.get_json() or {}
        from_token  = data.get("from_token")   # ETH/WETH/UJO
        to_token    = data.get("to_token")
        from_amount = data.get("from_amount")

        if not from_token or not to_token or from_amount is None:
            return jsonify({"error": "Insufficient data for exchange."}), 400

        try:
            from_amount = float(from_amount)
            if from_amount <= 0:
                raise ValueError
        except:
            return jsonify({"error": "Invalid from_amount."}), 400

        user_addr = user.unique_wallet_address
        user_pk   = user.unique_private_key

        # Special case 2: ETH -> WETH => then 0x swap WETH-> to_token
        if from_token.upper() == "ETH":
            # 1) Делаем deposit_eth_to_weth(...)
            logger.info(f"[exchange_tokens] user {user.id}: ETH->WETH deposit, amount={from_amount}")
            ok_deposit = deposit_eth_to_weth(user_pk, user_addr, from_amount)
            if not ok_deposit:
                return jsonify({"error":"Failed to wrap ETH to WETH. Possibly insufficient funds"}), 400

            # Теперь у нас есть WETH (from_token="WETH") => меняем WETH-> to_token
            from_token = "WETH"  # переопределяем
            logger.info(f"[exchange_tokens] user {user.id}: now WETH-> {to_token}")

        # Дальше идёт логика 0x swap
        chain_id = web3.eth.chain_id

        def to_0x_fmt(symbol:str)->str:
            if symbol.upper()=="ETH":
                # тут не должно попадать, т.к. ETH мы уже «завернули» 
                return "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
            elif symbol.upper()=="WETH":
                return weth_contract.address
            elif symbol.upper()=="UJO":
                return ujo_contract.address
            else:
                return symbol

        sell_token_0x = to_0x_fmt(from_token)
        buy_token_0x  = to_0x_fmt(to_token)

        decimals = 18
        sell_amount_wei = int(from_amount * (10 ** decimals))

        # Получаем котировку 0x
        quote = get_0x_quote_v2_permit2(
            sell_token_0x,
            buy_token_0x,
            sell_amount_wei,
            user_addr,
            chain_id
        )
        if not quote or "transaction" not in quote:
            return jsonify({"error":"Failed to get 0x quote."}), 400

        # Выполняем swap
        swap_ok = execute_0x_swap_v2_permit2(quote, user_pk)
        if not swap_ok:
            return jsonify({"error":"0x swap failed."}), 400

        buyAmount = 0.0
        if "buyAmount" in quote:
            buyAmount = float(quote["buyAmount"]) / (10**decimals)

        logger.info(f"[exchange_tokens] user {user.id}: {from_token} -> {to_token}, got ~{buyAmount}")
        return jsonify({"status":"success","ujo_received":buyAmount}), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"[exchange_tokens] exception: {e}", exc_info=True)
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
        totalRewards=0.0
        for s in stakings:
            if s.staked_amount > 0:
                delta = now - s.last_claim_at
                if delta >= timedelta(days=7):
                    totalRewards += s.pending_rewards
                    s.pending_rewards = 0.0
                    s.last_claim_at = now

        if totalRewards <= 0:
            return jsonify({"error":"Пока нечего клеймить"}), 400

        if not user.unique_wallet_address:
            return jsonify({"error":"No unique wallet address"}),400

        # Отправка наград от PROJECT_WALLET_ADDRESS
        ok = send_token_reward(
            to_address=user.unique_wallet_address,
            amount=totalRewards,
            private_key=PROJECT_PRIVATE_KEY  # Используем приватный ключ проекта
        )
        if not ok:
            db.session.rollback()
            return jsonify({"error":"Ошибка транзакции"}),400

        db.session.commit()
        return jsonify({"message": f"Claimed {totalRewards:.4f} UJO"}),200
    except CSRFError:
        return jsonify({"error":"CSRF token missing or invalid."}),400
    except Exception as e:
        logger.error(f"claim_staking_rewards_route exception: {e}", exc_info=True)
        return jsonify({"error":"Internal server error."}),500

@staking_bp.route('/api/unstake', methods=['POST'])
def unstake_staking_route():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error":"CSRF token missing"}),400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error":"Unauthorized"}),401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address:
            return jsonify({"error":"User not found or unique wallet set."}),400

        stakings = UserStaking.query.filter_by(user_id=user.id).all()
        total_unstake = 0.0
        now = datetime.utcnow()
        for s in stakings:
            if s.staked_amount > 0 and s.unlocked_at <= now:
                total_unstake += s.staked_amount
                s.staked_amount = 0.0
                s.staked_usd = 0.0
                s.pending_rewards = 0.0

        if total_unstake <= 0:
            return jsonify({"error":"Нет доступных стейков"}),400

        unstake_after_fee = total_unstake * 0.99
        fee = total_unstake * 0.01

        # Отправка токенов пользователю от PROJECT_WALLET_ADDRESS
        ok = send_token_reward(
            to_address=user.unique_wallet_address,
            amount=unstake_after_fee,
            private_key=PROJECT_PRIVATE_KEY  # Используем приватный ключ проекта
        )
        if not ok:
            db.session.rollback()
            return jsonify({"error":"send_token_reward failed"}),400

        if not PROJECT_WALLET_ADDRESS:
            db.session.rollback()
            return jsonify({"error":"PROJECT_WALLET_ADDRESS not set"}),500

        # Отправка комиссии от PROJECT_WALLET_ADDRESS
        fee_ok = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=fee,
            private_key=PROJECT_PRIVATE_KEY  # Используем приватный ключ проекта
        )
        if not fee_ok:
            db.session.rollback()
            return jsonify({"error":"Failed to send fee"}),400

        # Проверяем, остались ли активные стейки
        remaining = UserStaking.query.filter(
            UserStaking.user_id == user.id,
            UserStaking.staked_amount > 0
        ).count()
        if remaining == 0:
            user.assistant_premium = False

        db.session.commit()
        return jsonify({"message":f"Unstaked {total_unstake:.4f}, fee=1%, you got {unstake_after_fee:.4f}"}),200
    except CSRFError:
        return jsonify({"error":"CSRF token missing or invalid."}),400
    except Exception as e:
        logger.error(f"unstake_staking_route exception: {e}", exc_info=True)
        return jsonify({"error":"Internal server error."}),500

@staking_bp.route('/api/stake_tokens', methods=['POST'])
def stake_tokens():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error":"CSRF token missing."}),400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error":"Unauthorized"}),401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address:
            return jsonify({"error":"User not found or unique wallet set."}),404

        data = request.get_json() or {}
        amount_usd = data.get("amount_usd")
        if amount_usd is None:
            return jsonify({"error":"No amount_usd provided."}),400

        try:
            amount_usd = float(amount_usd)
            if amount_usd <= 0:
                raise ValueError
        except:
            return jsonify({"error":"Invalid amount_usd."}),400

        price_usd = get_token_price_in_usd()
        if not price_usd:
            return jsonify({"error":"Failed to get UJO price."}),400

        amount_ujo = amount_usd / price_usd

        # Отправка токенов от PROJECT_WALLET_ADDRESS пользователю
        ok = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=amount_ujo,
            private_key=PROJECT_PRIVATE_KEY  # Используем приватный ключ проекта
        )
        if not ok:
            return jsonify({"error":"Staking failed."}),400

        new_stake = UserStaking(
            user_id=user.id,
            tx_hash=f"staking_{datetime.utcnow().timestamp()}_{secrets.token_hex(8)}",
            staked_amount=amount_ujo,
            staked_usd=amount_usd,
            pending_rewards=0.0,
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow()+timedelta(days=30),
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_stake)
        db.session.commit()
        return jsonify({
            "status":"success",
            "staked_amount":amount_ujo,
            "staked_usd": amount_usd
        }),200

    except CSRFError:
        return jsonify({"error":"CSRF token missing or invalid."}),400
    except Exception as e:
        logger.error(f"stake_tokens error: {e}", exc_info=True)
        return jsonify({"error":"Internal server error."}),500

@staking_bp.route('/api/withdraw_funds', methods=['POST'])
def withdraw_funds():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error":"CSRF token missing."}),400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error":"Unauthorized"}),401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address or not user.wallet_address:
            return jsonify({"error":"User not found or wallet address not set."}),400

        bal = get_token_balance(user.unique_wallet_address, ujo_contract)
        if bal <= 0:
            return jsonify({"error":"No UJO tokens to withdraw."}),400

        # Отправка токенов пользователю от PROJECT_WALLET_ADDRESS
        ok = send_token_reward(
            to_address=user.wallet_address,
            amount=bal,
            private_key=PROJECT_PRIVATE_KEY  # Используем приватный ключ проекта
        )
        if ok:
            return jsonify({"status":"success"}),200
        else:
            return jsonify({"error":"Failed to send tokens."}),400

    except CSRFError:
        return jsonify({"error":"CSRF token missing or invalid."}),400
    except Exception as e:
        logger.error(f"withdraw_funds exception: {e}", exc_info=True)
        return jsonify({"error":"Internal server error."}),500
