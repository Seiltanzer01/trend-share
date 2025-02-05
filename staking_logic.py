# staking_logic.py

import os
import logging
import math
from datetime import datetime, timedelta
import requests
import secrets
import string
import sys
import json

from web3.exceptions import ContractCustomError
from web3 import Web3
from eth_account import Account

from models import db, User, UserStaking

logger = logging.getLogger(__name__)

# Обновленный RPC URL
BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://base-mainnet.public.blastapi.io")
web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

if not web3.is_connected():
    logger.error("Не удалось подключиться к RPC сети Base.")
    sys.exit(1)

# Переменные окружения для сети Base
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS", "0xYOUR_TOKEN_CONTRACT_ADDRESS")
WETH_CONTRACT_ADDRESS  = os.environ.get("WETH_CONTRACT_ADDRESS", "0xYOUR_WETH_CONTRACT_ADDRESS")
UJO_CONTRACT_ADDRESS   = TOKEN_CONTRACT_ADDRESS
PROJECT_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "0xYOUR_PROJECT_WALLET_ADDRESS")

# 1inch API настройки
ONEINCH_API_URL       = os.environ.get("ONEINCH_API_URL", "https://api.1inch.dev/swap/v6.0/8453")
ONEINCH_API_KEY       = os.environ.get("ONEINCH_API_KEY", "")
ONEINCH_ROUTER_ADDRESS= os.environ.get("ONEINCH_ROUTER_ADDRESS", "")

required_env_vars = [
    "TOKEN_CONTRACT_ADDRESS",
    "WETH_CONTRACT_ADDRESS",
    "MY_WALLET_ADDRESS",
    "PRIVATE_KEY",
    "DEXScreener_PAIR_ADDRESS",
    "ONEINCH_API_URL",
    "ONEINCH_API_KEY",
    "ONEINCH_ROUTER_ADDRESS"
]

missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
if missing_vars:
    logger.error(f"Отсутствуют необходимые переменные окружения: {', '.join(missing_vars)}")
    raise ValueError(f"Отсутствуют необходимые переменные окружения: {', '.join(missing_vars)}")

try:
    ONEINCH_ROUTER_ADDRESS = Web3.to_checksum_address(ONEINCH_ROUTER_ADDRESS)
    logger.info(f"ONEINCH_ROUTER_ADDRESS установлен на: {ONEINCH_ROUTER_ADDRESS}")
except Exception as e:
    logger.error(f"Invalid ONEINCH_ROUTER_ADDRESS: {ONEINCH_ROUTER_ADDRESS}. Error: {e}")
    raise ValueError(f"Invalid ONEINCH_ROUTER_ADDRESS: {ONEINCH_ROUTER_ADDRESS}. Error: {e}")

# ERC20 ABI
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
]

try:
    token_contract = web3.eth.contract(
        address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
        abi=ERC20_ABI
    )
    # Обновлённый ABI для WETH: функция withdraw теперь принимает аргумент "wad"
    weth_contract = web3.eth.contract(
        address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS),
        abi=ERC20_ABI + [
            {
                "constant": False,
                "inputs": [],
                "name": "deposit",
                "outputs": [],
                "payable": True,
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [{"name": "wad", "type": "uint256"}],
                "name": "withdraw",
                "outputs": [],
                "type": "function"
            },
        ]
    )
    ujo_contract = token_contract
    logger.info("Контракты успешно инициализированы.")
except Exception as e:
    logger.error(f"Ошибка инициализации контрактов: {e}", exc_info=True)
    sys.exit(1)

def generate_unique_wallet():
    while True:
        unique_private_key = generate_unique_private_key()
        acct = Account.from_key(unique_private_key)
        unique_wallet_address = Web3.to_checksum_address(acct.address)
        if not User.query.filter_by(unique_wallet_address=unique_wallet_address).first():
            return unique_wallet_address, unique_private_key

def generate_unique_private_key():
    return '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(64))

def verify_private_key(user: User) -> bool:
    try:
        acct = Account.from_key(user.unique_private_key)
        derived_address = Web3.to_checksum_address(acct.address)
        is_match = (derived_address.lower() == user.unique_wallet_address.lower())
        if not is_match:
            logger.error(f"Private key does not match wallet address for user {user.id}.")
        return is_match
    except Exception as e:
        logger.error(f"Verification failed for user {user.id}: {e}", exc_info=True)
        return False

def get_token_decimals(token_address: str) -> int:
    """
    Возвращаем decimals токена. 
    Для pseudo-ETH 0xEe... => 18.
    """
    try:
        if token_address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            return 18
        tmp = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        decimals = tmp.functions.decimals().call()
        logger.info(f"Token {token_address} has {decimals} decimals.")
        return decimals
    except Exception as e:
        logger.error(f"get_token_decimals error: {e}", exc_info=True)
        return 18

def get_token_balance(wallet_address: str, contract=None) -> float:
    """
    Если pseudo-ETH => web3.eth.get_balance, иначе contract.balanceOf().
    """
    try:
        if not contract:
            contract = token_contract

        # pseudo-ETH
        if contract.address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            raw_eth = web3.eth.get_balance(Web3.to_checksum_address(wallet_address))
            return float(Web3.from_wei(raw_eth, 'ether'))

        raw = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        dec = contract.functions.decimals().call()
        balance = raw / (10**dec)
        logger.info(f"Баланс кошелька {wallet_address}: {balance} токенов.")
        return balance
    except Exception as e:
        logger.error(f"get_token_balance error: {e}", exc_info=True)
        return 0.0

def send_token_reward(
    to_address: str,
    amount: float,
    from_address: str = PROJECT_WALLET_ADDRESS,
    private_key: str = None,
    token_contract_instance=None
) -> bool:
    """
    Отправляем `amount` токенов (по умолчанию UJO) с аккаунта private_key.
    Если private_key=None -> берём PROJECT_WALLET_ADDRESS из окружения.
    """
    try:
        if not token_contract_instance:
            token_contract_instance = token_contract

        if private_key:
            acct = Account.from_key(private_key)
        else:
            proj_pk = os.environ.get("PRIVATE_KEY", "")
            if not proj_pk:
                logger.error("PRIVATE_KEY не задан в переменных окружения.")
                return False
            acct = Account.from_key(proj_pk)

        # pseudo-ETH => отправка ETH напрямую
        if token_contract_instance.address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            return send_eth_from_user(private_key, to_address, amount)
        else:
            decimals = token_contract_instance.functions.decimals().call()
            amt_wei  = int(amount * (10**decimals))

            gas_price = web3.to_wei(0.1, 'gwei')
            gas_limit = 100000

            tx = token_contract_instance.functions.transfer(
                Web3.to_checksum_address(to_address),
                amt_wei
            ).build_transaction({
                "chainId": web3.eth.chain_id,
                "nonce":   web3.eth.get_transaction_count(acct.address, 'pending'),
                "gas":     gas_limit,
                "maxFeePerGas": gas_price,
                "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
                "value": 0
            })

            signed_tx = acct.sign_transaction(tx)
            tx_hash   = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt   = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

            if receipt.status == 1:
                logger.info(f"[send_token_reward] {amount} UJO -> {to_address}, tx={tx_hash.hex()}")
                return True
            else:
                logger.error(f"[send_token_reward] fail: {tx_hash.hex()}")
                return False
    except Exception as e:
        logger.error("send_token_reward except", exc_info=True)
        return False

def send_eth_from_user(user_private_key: str, to_address: str, amount_eth: float) -> bool:
    """
    Отправляем ETH c аккаунта user_private_key на to_address.
    """
    try:
        acct = Account.from_key(user_private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        gas_price = web3.to_wei(0.1, 'gwei')
        gas_limit = 21000

        tx = {
            "nonce":    nonce,
            "to":       Web3.to_checksum_address(to_address),
            "value":    web3.to_wei(amount_eth, 'ether'),
            "chainId":  web3.eth.chain_id,
            "gas":      gas_limit,
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
        }

        signed  = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        rcpt    = web3.eth.wait_for_transaction_receipt(tx_hash, 180)
        if rcpt.status == 1:
            logger.info(f"send_eth_from_user: {amount_eth} ETH -> {to_address}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"send_eth_from_user fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("send_eth_from_user error", exc_info=True)
        return False

def deposit_eth_to_weth(user_private_key: str, user_wallet: str, amount_eth: float) -> bool:
    """
    Заворачиваем ETH в WETH (путём вызова WETH.deposit).
    """
    try:
        acct = Account.from_key(user_private_key)
        balance_wei = web3.eth.get_balance(acct.address)
        eth_balance = float(Web3.from_wei(balance_wei, 'ether'))
        logger.info(f"User {acct.address} balance: {eth_balance} ETH")

        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        latest_block = web3.eth.get_block('latest')
        base_fee         = latest_block['baseFeePerGas']
        max_priority_fee = web3.to_wei(1, 'gwei')
        max_fee          = base_fee * 2 + max_priority_fee

        gas_price = web3.to_wei(0.1, 'gwei')
        gas_limit = 100000

        deposit_tx = weth_contract.functions.deposit().build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce":   nonce,
            "gas":     gas_limit,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority_fee,
            "value":  web3.to_wei(amount_eth, "ether"),
        })

        signed  = acct.sign_transaction(deposit_tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        rcpt    = web3.eth.wait_for_transaction_receipt(tx_hash, 180)

        if rcpt.status == 1:
            logger.info(f"deposit_eth_to_weth: {amount_eth} ETH -> WETH, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"deposit_eth_to_weth fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("deposit_eth_to_weth except", exc_info=True)
        return False

def get_balances(user: User) -> dict:
    """
    Возвращаем словарь с балансами ETH/WETH/UJO для уникального кошелька user.
    Балансы округляются вниз до 4 знаков после запятой и возвращаются как строки.
    """
    try:
        ua = Web3.to_checksum_address(user.unique_wallet_address)

        raw_eth = web3.eth.get_balance(ua)
        eth_bal = float(Web3.from_wei(raw_eth, 'ether'))
        eth_bal = math.floor(eth_bal * 1e4) / 1e4
        eth_str = format(eth_bal, ".4f")

        raw_w  = weth_contract.functions.balanceOf(ua).call()
        wdec   = weth_contract.functions.decimals().call()
        wbal   = raw_w / (10**wdec)
        wbal = math.floor(wbal * 1e4) / 1e4
        weth_str = format(wbal, ".4f")

        ujo_bal = get_token_balance(ua, ujo_contract)
        ujo_bal = math.floor(ujo_bal * 1e4) / 1e4
        ujo_str = format(ujo_bal, ".4f")

        return {
            "balances": {
                "eth": eth_str,
                "weth": weth_str,
                "ujo": ujo_str
            }
        }
    except Exception as e:
        logger.error(f"get_balances error: {e}", exc_info=True)
        return {"error": "Internal server error."}

def get_token_price_in_usd() -> float:
    """
    Запрашиваем DexScreener. Если не удалось — вернём 0.0
    """
    try:
        pair_address = os.environ.get("DEXScreener_PAIR_ADDRESS", "")
        if not pair_address:
            logger.error("DEXScreener_PAIR_ADDRESS не задан.")
            return 0.0

        chain_name = "base"
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"DexScreener code={resp.status_code}")
            return 0.0

        data = resp.json()
        pair = data.get("pair", {})
        if not pair:
            logger.warning("Пара не найдена на DexScreener.")
            return 0.0

        price_usd = pair.get("priceUsd", "0")
        if not price_usd:
            logger.warning("Цена USD не найдена в ответе DexScreener.")
            return 0.0

        logger.info(f"Цена UJO: {price_usd} USD")
        return float(price_usd)
    except Exception as e:
        logger.error(f"get_token_price_in_usd: {e}", exc_info=True)
        return 0.0

def approve_token(user_private_key: str, token_contract_instance, spender: str, amount: int) -> bool:
    """
    Approve для 1inch, если нужно.
    """
    try:
        acct = Account.from_key(user_private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        gas_price = web3.to_wei(0.1, 'gwei')
        gas_limit = 100000

        approve_tx = token_contract_instance.functions.approve(
            spender, amount
        ).build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce": nonce,
            "gas": gas_limit,
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
            "value": 0,
        })

        signed_tx = acct.sign_transaction(approve_tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        if receipt.status == 1:
            logger.info(f"approve_token ok, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"approve_token fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("approve_token except", exc_info=True)
        return False

def swap_tokens_via_1inch(user_private_key: str, from_token: str, to_token: str, amount: float) -> bool:
    """
    Если нужно свапать через 1inch.
    """
    try:
        acct = Account.from_key(user_private_key)
        user_address = Web3.to_checksum_address(acct.address)

        is_eth = (from_token.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
        if not is_eth:
            from_token_contract = web3.eth.contract(
                address=Web3.to_checksum_address(from_token),
                abi=ERC20_ABI
            )
            decimals = from_token_contract.functions.decimals().call()
            amount_in = int(amount * (10**decimals))

            curr_allow = from_token_contract.functions.allowance(user_address, ONEINCH_ROUTER_ADDRESS).call()
            if curr_allow < amount_in:
                if not approve_token(user_private_key, from_token_contract, ONEINCH_ROUTER_ADDRESS, amount_in):
                    return False

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ONEINCH_API_KEY}" if ONEINCH_API_KEY else "",
            "Accept": "application/json"
        }
        swap_endpoint = f"{ONEINCH_API_URL}/swap"

        dec_from = 18 if is_eth else get_token_decimals(from_token)
        amt_str = str(int(amount * (10**dec_from)))
        params = {
            "fromTokenAddress": from_token,
            "toTokenAddress": to_token,
            "amount": amt_str,
            "fromAddress": user_address,
            "slippage": "1",
            "disableEstimate": False,
            "allowPartialFill": False
        }

        resp = requests.get(swap_endpoint, params=params, headers=headers)
        if resp.status_code != 200:
            return False

        swap_data = resp.json()
        if 'tx' not in swap_data:
            return False

        tx = swap_data['tx']

        latest_block = web3.eth.get_block('latest')
        base_fee = latest_block['baseFeePerGas']
        max_priority_fee = web3.to_wei(1, 'gwei')
        max_fee = base_fee * 2 + max_priority_fee

        txn = {
            'to': Web3.to_checksum_address(tx['to']),
            'data': tx['data'],
            'value': int(tx['value']),
            'gas': int(tx['gas']),
            'nonce': web3.eth.get_transaction_count(user_address, 'pending'),
            'chainId': web3.eth.chain_id,
            'type': 2,
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': max_priority_fee
        }

        signed_tx = acct.sign_transaction(txn)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, 180)

        return (receipt.status == 1)

    except Exception as e:
        logger.error("[swap_tokens_via_1inch] except", exc_info=True)
        return False

def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """
    Если транзакция >= 25$ => создаём запись в UserStaking + assistant_premium = True.
    (В ТЕСТЕ: >= 0.5$)
    
    Но ВНИМАНИЕ! Если пользователь отправляет UJO => проекту,
    тогда мы ищем from_addr == user.unique_wallet_address 
                 and to_addr   == PROJECT_WALLET_ADDRESS.
    """
    if not user or not tx_hash:
        return False
    try:
        receipt = web3.eth.get_transaction_receipt(tx_hash)
        if not receipt or receipt.status != 1:
            logger.error(f"Tx not found or fail: {tx_hash}")
            return False

        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        price_usd = get_token_price_in_usd()
        if price_usd <= 0:
            return False

        found = None
        for lg in receipt.logs:
            if lg.address.lower() == token_contract.address.lower():
                if len(lg.topics) >= 3 and lg.topics[0].hex().lower() == transfer_topic.lower():
                    from_addr = "0x" + lg.topics[1].hex()[26:]
                    to_addr = "0x" + lg.topics[2].hex()[26:]
                    from_addr = Web3.to_checksum_address(from_addr)
                    to_addr = Web3.to_checksum_address(to_addr)

                    # Ищем именно user -> project (в тесте 0.5$, в основном 25$).
                    if from_addr.lower() == user.unique_wallet_address.lower() and \
                       to_addr.lower() == PROJECT_WALLET_ADDRESS.lower():
                        amt_int = int(lg.data, 16)
                        token_decimals = get_token_decimals(token_contract.address)
                        token_amt = amt_int / (10**token_decimals)
                        usd_amt = token_amt * price_usd
                        logger.info(f"[confirm_staking_tx] found {token_amt} UJO => ~{usd_amt} USD")
                        if usd_amt >= 0.5:  # или 25
                            found = {"token_amount": token_amt, "usd_amount": usd_amt}
                            break

        if not found:
            logger.warning("Not found an appropriate Transfer in logs.")
            return False

        # Проверка на дубликат
        ex = UserStaking.query.filter_by(tx_hash=tx_hash).first()
        if ex:
            logger.warning(f"Tx {tx_hash} already in DB.")
            return False

        # Создаём запись
        new_s = UserStaking(
            user_id=user.id,
            tx_hash=tx_hash,
            staked_usd=found["usd_amount"],
            staked_amount=found["token_amount"],
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow() + timedelta(days=30),  # или 5 минут в тесте
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_s)

        # Активируем premium
        user.assistant_premium = True

        db.session.commit()

        logger.info(f"User {user.id}: staked ~{found['usd_amount']:.2f}$ => premium ON.")
        return True

    except Exception as e:
        db.session.rollback()
        logger.error(f"[confirm_staking_tx] except: {e}", exc_info=True)
        return False

def accumulate_staking_rewards():
    """
    Каждую минуту: + (12% / 525600) * staked_amount
    """
    try:
        st = UserStaking.query.all()
        minute_rate = 0.12 / 525600  # 12%/год
        for s in st:
            if s.staked_amount > 0:
                s.pending_rewards += s.staked_amount * minute_rate
        db.session.commit()
        logger.info("accumulate_staking_rewards: Rewards added successfully.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"accumulate_staking_rewards except: {e}", exc_info=True)
