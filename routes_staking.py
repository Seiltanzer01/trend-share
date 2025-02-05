# routes_staking.py

import logging
import traceback
import os
from datetime import datetime, timedelta
import secrets
import string
import time
import requests  # Импорт для работы с HTTP запросами

from flask import Blueprint, request, jsonify, session, render_template, flash, redirect, url_for
from flask_wtf.csrf import validate_csrf, CSRFError
from web3 import Web3
from models import db, User, UserStaking
from staking_logic import (
    confirm_staking_tx,
    get_token_balance,
    get_token_price_in_usd,
    get_token_decimals,  # Функция для получения decimals токена
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
    deposit_eth_to_weth,
    verify_private_key,
    send_eth_from_user,
)
from best_setup_voting import send_token_reward as voting_send_token_reward  # For compatibility

logger = logging.getLogger(__name__)
staking_bp = Blueprint('staking_bp', __name__)

# Адрес TokenTransferProxy для ParaSwap (можно задать в переменной окружения)
PARASWAP_PROXY_ADDRESS = os.environ.get("PARASWAP_PROXY_ADDRESS", "0x6a000f20005980200259b80c5102003040001068")

def unwrap_weth_to_eth(private_key, user_address, amount_eth):
    """
    Разворачивает WETH в ETH, вызывая метод withdraw(wad) у контракта WETH.
    :param private_key: Приватный ключ пользователя.
    :param user_address: Адрес пользователя.
    :param amount_eth: Сумма в ETH для разворачивания.
    :return: True при успешном выполнении, иначе False.
    """
    try:
        amount_wei = int(amount_eth * 10**18)
        nonce = web3.eth.get_transaction_count(user_address)
        tx = weth_contract.functions.withdraw(amount_wei).build_transaction({
            "from": user_address,
            "nonce": nonce,
            "gas": 100000,
            "gasPrice": web3.to_wei(0.1, "gwei"),
            "chainId": web3.eth.chain_id
        })
        signed_tx = web3.eth.account.sign_transaction(tx, private_key)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"WETH to ETH unwrap transaction sent, tx_hash: {Web3.to_hex(tx_hash)}")
        return True
    except Exception as e:
        logger.error(f"unwrap_weth_to_eth exception: {e}", exc_info=True)
        return False

def swap_tokens_via_paraswap(private_key, sell_token, buy_token, from_amount, user_address):
    """
    Обмен токенов через API ParaSwap v6.2.
    
    Шаг 1: Получение котировки (quote) от ParaSwap.
    Шаг 2: Построение данных транзакции через POST запрос.
    Шаг 3: Подпись и отправка транзакции через web3.
    
    Если котировка не получена, используется fallback – рыночная котировка.
    
    :param private_key: Приватный ключ отправителя.
    :param sell_token: Адрес исходного токена.
    :param buy_token: Адрес токена, в который производится обмен.
    :param from_amount: Сумма обмена в единицах токена.
    :param user_address: Адрес отправителя.
    :return: True при успешном выполнении обмена, иначе False.
    """
    try:
        logger.info("=== swap_tokens_via_paraswap START ===")
        # Определяем srcDecimals и destDecimals
        if sell_token.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            src_decimals = 18
        else:
            src_decimals = get_token_decimals(sell_token)
        if buy_token.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            dest_decimals = 18
        else:
            dest_decimals = get_token_decimals(buy_token)
        logger.info(f"Source decimals: {src_decimals}, Destination decimals: {dest_decimals}")

        # Преобразуем from_amount в минимальные единицы (например, wei)
        from_amount_units = int(from_amount * 10 ** src_decimals)
        logger.info(f"Converted from_amount: {from_amount} -> {from_amount_units} units")

        # Получаем chainId из web3
        chain_id = web3.eth.chain_id
        logger.info(f"Using chain id: {chain_id}")

        # Получаем базовый URL для ParaSwap
        PARASWAP_API_URL = os.environ.get("PARASWAP_API_URL", "https://api.paraswap.io")
        version = "6.2"
        logger.info(f"Using ParaSwap API URL: {PARASWAP_API_URL} with version {version}")

        # Шаг 1: Получение котировки с режимом "market"
        quote_url = f"{PARASWAP_API_URL}/quote?version={version}"
        params = {
            "srcToken": sell_token,
            "destToken": buy_token,
            "amount": str(from_amount_units),
            "userAddress": user_address,
            "side": "SELL",
            "srcDecimals": src_decimals,
            "destDecimals": dest_decimals,
            "chainId": chain_id,
            "mode": "market"
        }
        logger.info(f"Sending GET request to {quote_url} with params: {params}")
        quote_response = requests.get(quote_url, params=params)
        logger.info(f"Quote response status code: {quote_response.status_code}")
        if quote_response.status_code != 200:
            logger.error(f"ParaSwap quote error: {quote_response.text}")
            return False
        quote_data = quote_response.json()
        logger.info(f"Quote data received: {quote_data}")

        # Если ключ 'priceRoute' отсутствует, используем 'market'
        price_route = quote_data.get("priceRoute")
        if not price_route:
            logger.warning("Delta priceRoute not found; attempting to use market priceRoute fallback.")
            price_route = quote_data.get("market")
            if not price_route:
                logger.error("No valid priceRoute found in ParaSwap quote response.")
                return False
            else:
                logger.info("Using market priceRoute as fallback.")

        # Шаг 2: Построение данных транзакции.
        tx_url = f"{PARASWAP_API_URL}/transactions/{chain_id}"
        tx_payload = {
            "srcToken": sell_token,
            "destToken": buy_token,
            "srcAmount": str(from_amount_units),
            "userAddress": user_address,
            "priceRoute": price_route,
            "slippage": 1000
        }
        logger.info(f"Sending POST request to {tx_url} with payload: {tx_payload}")
        tx_response = requests.post(tx_url, json=tx_payload)
        logger.info(f"Transaction response status code: {tx_response.status_code}")
        if tx_response.status_code != 200:
            logger.error(f"ParaSwap transaction build error: {tx_response.text}")
            return False
        tx_data = tx_response.json()
        logger.info(f"Transaction data received: {tx_data}")

        # Шаг 3: Подготовка и отправка транзакции через web3.
        to_address = Web3.to_checksum_address(tx_data["to"])
        nonce = web3.eth.get_transaction_count(user_address)
        logger.info(f"Obtained nonce: {nonce} for address: {user_address}")
        transaction = {
            "to": to_address,
            "data": tx_data["data"],
            "value": int(tx_data["value"]),
            "gasPrice": int(tx_data["gasPrice"]),
            "gas": int(tx_data["gas"]),
            "nonce": nonce
        }
        logger.info(f"Final transaction data: {transaction}")
        signed_tx = web3.eth.account.sign_transaction(transaction, private_key)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"ParaSwap transaction sent, tx_hash: {Web3.to_hex(tx_hash)}")
        logger.info("=== swap_tokens_via_paraswap END ===")
        return True
    except Exception as e:
        logger.error(f"swap_tokens_via_paraswap exception: {e}", exc_info=True)
        return False

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
        temp_user = User(
            unique_wallet_address=unique_wallet_address,
            unique_private_key=unique_private_key
        )
        if not verify_private_key(temp_user):
            return jsonify({"error": "Generated private key does not match the wallet address."}), 500
        user.unique_wallet_address = unique_wallet_address
        user.unique_private_key = unique_private_key
        db.session.commit()
        logger.info(f"Unique wallet {unique_wallet_address} for user_id={user_id}")
        return jsonify({"status": "success", "unique_wallet_address": unique_wallet_address}), 200
    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Error in generate_unique_wallet_route: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/deposit', methods=['GET'])
def deposit_page():
    if 'user_id' not in session:
        flash('Please log in for deposit.', 'warning')
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('login'))
    return render_template('deposit.html', unique_wallet_address=user.unique_wallet_address)

@staking_bp.route('/subscription', methods=['GET'])
def subscription_page():
    if 'user_id' not in session:
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('login'))
    if not user.unique_wallet_address:
        flash('Please generate your wallet.', 'warning')
        return redirect(url_for('staking_bp.generate_unique_wallet_route'))
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
            return jsonify({"error": "User not found."}), 404
        data = request.get_json() or {}
        tx_hash = data.get("txHash")
        if not tx_hash:
            return jsonify({"error": "No txHash provided"}), 400
        ok = confirm_staking_tx(user, tx_hash)
        if ok:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Staking confirmation failed"}), 400
    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Error in confirm_staking: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/get_user_stakes', methods=['GET'])
def get_user_stakes():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({"error": "User not found."}), 404
    try:
        stakings = UserStaking.query.filter_by(user_id=user.id).all()
        stakes_data = []
        for s in stakings:
            if s.staked_amount > 0:
                stakes_data.append({
                    'tx_hash': s.tx_hash,
                    'staked_amount': float(s.staked_amount),
                    'staked_usd': float(s.staked_usd),
                    'pending_rewards': float(s.pending_rewards),
                    'unlocked_at': int(s.unlocked_at.timestamp() * 1000)
                })
        return jsonify({"stakes": stakes_data}), 200
    except Exception as e:
        logger.error(f"Error in get_user_stakes: {e}", exc_info=True)
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
    Обмен токенов через ParaSwap.
    Если в качестве исходного токена указан ETH, сначала оборачиваем ETH в WETH.
    Если целевой токен равен ETH и исходный – WETH, выполняется операция unwrap (WETH -> ETH).
    Если обмен осуществляется с UJO, проверяется allowance для TokenTransferProxy.
    Также, если обмен производится из ETH в WETH, повторное оборачивание не выполняется.
    """
    try:
        logger.info("=== exchange_tokens START ===")
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.error("CSRF token missing in exchange_tokens request.")
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)
        if 'user_id' not in session:
            logger.error("Unauthorized access in exchange_tokens.")
            return jsonify({"error": "Unauthorized"}), 401
        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address:
            logger.error("User not found or unique wallet not set in exchange_tokens.")
            return jsonify({"error": "User not found or unique wallet not set."}), 404
        data = request.get_json() or {}
        from_token_symbol = data.get("from_token")
        to_token_symbol = data.get("to_token")
        from_amount = data.get("from_amount")
        if not from_token_symbol or not to_token_symbol or from_amount is None:
            logger.error("Insufficient data for exchange in exchange_tokens.")
            return jsonify({"error": "Insufficient data for exchange."}), 400
        try:
            from_amount = float(from_amount)
            if from_amount <= 0:
                raise ValueError
        except ValueError:
            logger.error(f"Invalid from_amount value: {from_amount}")
            return jsonify({"error": "Invalid value for from_amount."}), 400

        # Функция для определения адреса токена по символу.
        def get_token_address(symbol: str) -> str:
            symbol_upper = symbol.upper()
            if symbol_upper == "ETH":
                logger.info("Received ETH as source token – switching to WETH address for swap.")
                return WETH_CONTRACT_ADDRESS
            elif symbol_upper == "WETH":
                return WETH_CONTRACT_ADDRESS
            elif symbol_upper == "UJO":
                return UJO_CONTRACT_ADDRESS
            else:
                return symbol

        # Если исходный токен указан как ETH, оборачиваем его в WETH (но не если уже достаточно WETH)
        if from_token_symbol.upper() == "ETH":
            logger.info("Detected ETH as source token. Initiating wrapping (deposit) to WETH.")
            eth_balance = float(Web3.from_wei(web3.eth.get_balance(user.unique_wallet_address), 'ether'))
            logger.info(f"User ETH balance: {eth_balance} ETH")
            if eth_balance < from_amount:
                logger.error("Insufficient ETH balance for wrapping.")
                return jsonify({"error": "Insufficient ETH balance for wrapping."}), 400
            current_weth = get_token_balance(user.unique_wallet_address, weth_contract)
            if current_weth < from_amount:
                wrap_success = deposit_eth_to_weth(user.unique_private_key, user.unique_wallet_address, from_amount)
                if not wrap_success:
                    logger.error("Failed to wrap ETH to WETH.")
                    return jsonify({"error": "Failed to wrap ETH to WETH."}), 400
                else:
                    logger.info("Successfully wrapped ETH to WETH.")
            if to_token_symbol.upper() == "WETH":
                logger.info("Exchange ETH to WETH requested; deposit operation completed, returning balances.")
                result = get_balances(user)
                return jsonify({"status": "success", "balances": result["balances"]}), 200
            effective_from_token = "WETH"
        else:
            effective_from_token = from_token_symbol

        # Если обмен WETH -> ETH, выполняем операцию unwrap
        if effective_from_token.upper() == "WETH" and to_token_symbol.upper() == "ETH":
            logger.info("Exchange WETH to ETH requested; initiating unwrap process.")
            current_weth = get_token_balance(user.unique_wallet_address, weth_contract)
            if current_weth < from_amount - 1e-12:
                logger.error("Insufficient WETH balance for unwrap.")
                return jsonify({"error": "Insufficient WETH balance for unwrap."}), 400
            unwrap_success = unwrap_weth_to_eth(user.unique_private_key, user.unique_wallet_address, from_amount)
            if unwrap_success:
                logger.info("Successfully unwrapped WETH to ETH.")
                result = get_balances(user)
                return jsonify({"status": "success", "balances": result["balances"]}), 200
            else:
                logger.error("Error executing unwrap (WETH to ETH).")
                return jsonify({"error": "Error executing unwrap (WETH to ETH)."}), 400

        # Если источник UJO, проверяем allowance для TokenTransferProxy
        if effective_from_token.upper() == "UJO":
            allowance = token_contract.functions.allowance(
                Web3.to_checksum_address(user.unique_wallet_address),
                Web3.to_checksum_address(PARASWAP_PROXY_ADDRESS)
            ).call()
            logger.info(f"Current UJO allowance for proxy {PARASWAP_PROXY_ADDRESS}: {allowance}")
            required_amount = int(from_amount * 10 ** get_token_decimals(UJO_CONTRACT_ADDRESS))
            if allowance < required_amount:
                logger.info("Allowance insufficient for UJO, initiating approve transaction.")
                max_allowance = 2**256 - 1
                approve_tx = token_contract.functions.approve(
                    Web3.to_checksum_address(PARASWAP_PROXY_ADDRESS),
                    max_allowance
                ).build_transaction({
                    "from": Web3.to_checksum_address(user.unique_wallet_address),
                    "nonce": web3.eth.get_transaction_count(Web3.to_checksum_address(user.unique_wallet_address), "pending"),
                    "gas": 100000,
                    "gasPrice": web3.to_wei(0.1, "gwei"),
                    "chainId": web3.eth.chain_id
                })
                logger.info(f"UJO approve transaction built: {approve_tx}")
                signed_approve_tx = web3.eth.account.sign_transaction(approve_tx, user.unique_private_key)
                approve_tx_hash = web3.eth.send_raw_transaction(signed_approve_tx.rawTransaction)
                logger.info(f"UJO approve transaction sent, tx_hash: {Web3.to_hex(approve_tx_hash)}")
                web3.eth.wait_for_transaction_receipt(approve_tx_hash, timeout=180)
        # Если источник WETH, проверяем allowance
        if effective_from_token.upper() == "WETH":
            allowance = weth_contract.functions.allowance(
                Web3.to_checksum_address(user.unique_wallet_address),
                Web3.to_checksum_address(PARASWAP_PROXY_ADDRESS)
            ).call()
            logger.info(f"Current WETH allowance for proxy {PARASWAP_PROXY_ADDRESS}: {allowance}")
            required_amount = int(from_amount * 10 ** get_token_decimals(WETH_CONTRACT_ADDRESS))
            if allowance < required_amount:
                logger.info("Allowance insufficient, initiating approve transaction using raw signed transaction.")
                max_allowance = 2**256 - 1
                approve_tx = weth_contract.functions.approve(
                    Web3.to_checksum_address(PARASWAP_PROXY_ADDRESS),
                    max_allowance
                ).build_transaction({
                    "from": Web3.to_checksum_address(user.unique_wallet_address),
                    "nonce": web3.eth.get_transaction_count(Web3.to_checksum_address(user.unique_wallet_address), "pending"),
                    "gas": 100000,
                    "gasPrice": web3.to_wei(0.1, "gwei"),
                    "chainId": web3.eth.chain_id
                })
                logger.info(f"Approve transaction built: {approve_tx}")
                signed_approve_tx = web3.eth.account.sign_transaction(approve_tx, user.unique_private_key)
                approve_tx_hash = web3.eth.send_raw_transaction(signed_approve_tx.rawTransaction)
                logger.info(f"Approve transaction sent, tx_hash: {Web3.to_hex(approve_tx_hash)}")
            else:
                logger.info("Sufficient allowance exists for WETH.")

        # Выполнение обмена через ParaSwap
        sell_token = get_token_address(effective_from_token)
        buy_token = get_token_address(to_token_symbol)
        logger.info(f"Exchange: {from_amount} {from_token_symbol} (using {sell_token}) -> {to_token_symbol} ({buy_token})")

        # Проверка баланса пользователя для исходного токена
        if effective_from_token.upper() == "WETH":
            user_balance = get_token_balance(user.unique_wallet_address, weth_contract)
            logger.info(f"User WETH balance: {user_balance}")
            if user_balance < from_amount:
                logger.error("Insufficient WETH for exchange.")
                return jsonify({"error": "Insufficient WETH for exchange."}), 400
        else:
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
            logger.info(f"User {effective_from_token} balance: {user_balance}")
            if user_balance < from_amount:
                logger.error(f"Insufficient {effective_from_token} for exchange.")
                return jsonify({"error": f"Insufficient {effective_from_token} for exchange."}), 400

        swap_ok = swap_tokens_via_paraswap(
            user.unique_private_key,
            sell_token,
            buy_token,
            from_amount,
            user.unique_wallet_address
        )
        if not swap_ok:
            logger.error("Error executing exchange via ParaSwap.")
            return jsonify({"error": "Error executing exchange via ParaSwap."}), 400

        result = get_balances(user)
        if "error" in result:
            logger.error(f"Error in get_balances: {result['error']}")
            return jsonify({"error": result["error"]}), 500

        logger.info(f"Successful exchange: {from_token_symbol} -> {to_token_symbol}, amount: {from_amount}")
        logger.info("=== exchange_tokens END ===")
        return jsonify({
            "status": "success",
            "balances": result["balances"]
        }), 200

    except CSRFError:
        logger.error("CSRF token missing or invalid in exchange_tokens.")
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error(f"Error in exchange_tokens: {e}", exc_info=True)
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
            return jsonify({"error": "You have no staking."}), 400
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
            return jsonify({"error": "Nothing to claim yet."}), 400
        if not user.unique_wallet_address:
            return jsonify({"error": "No unique wallet address"}), 400
        ok = send_token_reward(
            to_address=user.unique_wallet_address,
            amount=totalRewards,
            private_key=os.environ.get("PRIVATE_KEY")
        )
        if not ok:
            db.session.rollback()
            return jsonify({"error": "Transaction error."}), 400
        db.session.commit()
        return jsonify({"message": f"Claimed {totalRewards:.4f} UJO"}), 200
    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error("claim_staking_rewards_route exception", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

@staking_bp.route('/api/unstake', methods=['POST'])
def unstake_staking_route():
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
            return jsonify({"error": "No available stakes for unstake."}), 400
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
            return jsonify({"error": "Error sending UJO to your wallet."}), 400
        fee_success = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=fee,
            private_key=os.environ.get("PRIVATE_KEY"),
            token_contract_instance=token_contract
        )
        if not fee_success:
            db.session.rollback()
            return jsonify({"error": "Error sending fee."}), 400
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
# PLEASE NOTE: This is a TEST: $0.5 => (0.2 + 0.3)
###################################################################
@staking_bp.route('/api/stake_tokens', methods=['POST'])
def stake_tokens_route():
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
        active_stake = UserStaking.query.filter(
            UserStaking.user_id == user.id,
            UserStaking.staked_amount > 0
        ).first()
        if active_stake:
            return jsonify({"error": "You already have an active stake. Another stake is not allowed."}), 400
        data = request.get_json() or {}
        total_usd = data.get("amount_usd")
        if total_usd is None:
            return jsonify({"error": "No amount_usd provided."}), 400
        try:
            total_usd = float(total_usd)
            if total_usd < 12:
                return jsonify({"error": "Exactly $0.5 is required (test mode)."}), 400
        except ValueError:
            return jsonify({"error": "Invalid amount_usd."}), 400
        stake_usd = 10
        fee_usd = 2
        price_usd = get_token_price_in_usd()
        if not price_usd or price_usd <= 0:
            return jsonify({"error": "Failed to get UJO price."}), 400
        fee_ujo = fee_usd / price_usd
        stake_ujo = stake_usd / price_usd
        total_need_ujo = fee_ujo + stake_ujo
        user_balance = get_token_balance(user.unique_wallet_address, token_contract)
        if user_balance < total_need_ujo:
            return jsonify({"error": "Insufficient UJO in wallet (test $0.5 required)."}), 400
        ok_fee = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=fee_ujo,
            private_key=user.unique_private_key,
            token_contract_instance=token_contract
        )
        if not ok_fee:
            return jsonify({"error": "Error sending $0.2 (fee)."}), 400
        ok_stake = send_token_reward(
            to_address=PROJECT_WALLET_ADDRESS,
            amount=stake_ujo,
            private_key=user.unique_private_key,
            token_contract_instance=token_contract
        )
        if not ok_stake:
            return jsonify({"error": "Error sending $0.3 (stake)."}), 400
        new_stake = UserStaking(
            user_id=user.id,
            tx_hash=f"staking_{datetime.utcnow().timestamp()}_{secrets.token_hex(8)}",
            staked_amount=stake_ujo,
            staked_usd=stake_usd,
            pending_rewards=0.0,
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow() + timedelta(days=30),
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_stake)
        user.assistant_premium = True
        db.session.commit()
        logger.info(f"[TEST stake] user={user.id}, fee=$0.2, stake=$0.3")
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
            return jsonify({"error": "Insufficient data for withdrawal."}), 400
        token = token.upper()
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid withdrawal amount."}), 400
        balances_dict = get_balances(user)
        if "error" in balances_dict:
            return jsonify({"error": balances_dict["error"]}), 500
        # Округляем баланс вниз до 6 знаков
        available_balance = float((int(balances_dict["balances"].get(token.lower(), 0) * 1e6)) / 1e6)
        if available_balance < amount:
            return jsonify({"error": f"Insufficient {token} for withdrawal."}), 400
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
            return jsonify({"error": "Unsupported coin for withdrawal."}), 400
        if success:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Failed to withdraw funds."}), 400
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
