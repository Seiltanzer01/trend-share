# staking_logic.py

import os
import logging
from datetime import datetime, timedelta
import requests
import secrets
import string
import sys
import binascii
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
WETH_CONTRACT_ADDRESS = os.environ.get("WETH_CONTRACT_ADDRESS", "0xYOUR_WETH_CONTRACT_ADDRESS")
UJO_CONTRACT_ADDRESS = TOKEN_CONTRACT_ADDRESS
PROJECT_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "0xYOUR_PROJECT_WALLET_ADDRESS")

# 1inch API настройки
ONEINCH_API_URL = os.environ.get("ONEINCH_API_URL", "https://api.1inch.dev/swap/v6.0/8453")  # Используем chain_id=8453 для Base
ONEINCH_API_KEY = os.environ.get("ONEINCH_API_KEY", "")  # Если требуется API ключ
ONEINCH_ROUTER_ADDRESS = os.environ.get("ONEINCH_ROUTER_ADDRESS", "")  # Добавлено

# Проверьте, что переменные окружения установлены корректно
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

# Преобразуем ONEINCH_ROUTER_ADDRESS в checksum формат
try:
    ONEINCH_ROUTER_ADDRESS = Web3.to_checksum_address(ONEINCH_ROUTER_ADDRESS)
    logger.info(f"ONEINCH_ROUTER_ADDRESS установлен на: {ONEINCH_ROUTER_ADDRESS}")
except Exception as e:
    logger.error(f"Invalid ONEINCH_ROUTER_ADDRESS: {ONEINCH_ROUTER_ADDRESS}. Error: {e}")
    raise ValueError(f"Invalid ONEINCH_ROUTER_ADDRESS: {ONEINCH_ROUTER_ADDRESS}. Error: {e}")

# ERC20 ABI с необходимыми функциями
ERC20_ABI = [
    # balanceOf
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    # transfer
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
    # decimals
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    # allowance
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
    # approve
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

# Инициализация контрактов
try:
    token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS), abi=ERC20_ABI)
    weth_contract = web3.eth.contract(address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS), abi=ERC20_ABI + [
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
            "inputs": [],
            "name": "withdraw",
            "outputs": [],
            "type": "function"
        },
    ])
    ujo_contract = token_contract  # Используем только token_contract
    logger.info("Контракты успешно инициализированы.")
except Exception as e:
    logger.error(f"Ошибка инициализации контрактов: {e}", exc_info=True)
    sys.exit(1)

def generate_unique_wallet():
    """
    Генерирует уникальный приватный ключ и соответствующий ему адрес кошелька.
    """
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
        is_match = derived_address.lower() == user.unique_wallet_address.lower()
        if not is_match:
            logger.error(f"Private key does not match wallet address for user {user.id}.")
        return is_match
    except Exception as e:
        logger.error(f"Verification failed for user {user.id}: {e}", exc_info=True)
        return False

def get_token_decimals(token_address: str) -> int:
    """
    Получает количество десятичных знаков токена по его адресу.
    """
    try:
        token = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        decimals = token.functions.decimals().call()
        logger.info(f"Token {token_address} has {decimals} decimals.")
        return decimals
    except Exception as e:
        logger.error(f"get_token_decimals error: {e}", exc_info=True)
        return 18  # Default to 18 decimals if not found

def get_token_balance(wallet_address: str, contract=None) -> float:
    """
    Получает баланс указанного токена (по умолчанию - UJO).
    """
    try:
        if contract is None:
            contract = ujo_contract
        raw = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        dec = contract.functions.decimals().call()
        balance = raw / (10 ** dec)
        logger.info(f"Баланс кошелька {wallet_address}: {balance} токенов.")
        return balance
    except Exception as e:
        logger.error(f"get_token_balance error: {e}", exc_info=True)
        return 0.0

def send_token_reward(
    to_address: str,
    amount: float,
    from_address: str = PROJECT_WALLET_ADDRESS,
    private_key: str = None
) -> bool:
    """
    Отправляет токены с PROJECT_WALLET_ADDRESS пользователю.
    """
    try:
        if private_key:
            acct = Account.from_key(private_key)
        else:
            proj_pk = os.environ.get("PRIVATE_KEY", "")
            if not proj_pk:
                logger.error("PRIVATE_KEY не задан.")
                return False
            acct = Account.from_key(proj_pk)

        decimals = token_contract.functions.decimals().call()
        amt_wei = int(amount * (10 ** decimals))

        # Параметры газа для сети Base установлены на 0.1 gwei
        gas_price = web3.to_wei(0.1, 'gwei')  # Установлено на 0.1 gwei
        gas_limit = 100000  # Стандартный gas limit для transfer

        tx = token_contract.functions.transfer(
            Web3.to_checksum_address(to_address),
            amt_wei
        ).build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce": web3.eth.get_transaction_count(acct.address, 'pending'),
            "gas": gas_limit,
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
            "value": 0,
            "from": acct.address  # Добавлено поле "from"
        })
        signed_tx = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        if receipt.status == 1:
            logger.info(f"send_token_reward: {amount} UJO -> {to_address}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"send_token_reward fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("send_token_reward except", exc_info=True)
        return False

def send_eth(to_address: str, amount_eth: float, private_key: str) -> bool:
    """
    Отправка нативного ETH (для gas и т.п.) с настройкой параметров газа.
    """
    try:
        acct = Account.from_key(private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        # Параметры газа установлены на 0.1 gwei
        gas_price = web3.to_wei(0.1, 'gwei')  # Установлено на 0.1 gwei
        gas_limit = 21000  # Стандартный gas limit для ETH

        tx = {
            "nonce": nonce,
            "to": Web3.to_checksum_address(to_address),
            "value": web3.to_wei(amount_eth, 'ether'),
            "chainId": web3.eth.chain_id,
            "gas": gas_limit,
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
            "from": acct.address  # Добавлено поле "from"
        }
        signed = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, 180)
        if receipt.status == 1:
            logger.info(f"send_eth: {amount_eth} ETH -> {to_address}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"send_eth fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("send_eth error", exc_info=True)
        return False

def deposit_eth_to_weth(user_private_key: str, user_wallet: str, amount_eth: float) -> bool:
    """
    Выполняет WETH.deposit(), «заворачивая» заданное количество ETH в WETH.
    """
    try:
        acct = Account.from_key(user_private_key)
        balance_wei = web3.eth.get_balance(acct.address)
        eth_balance = Web3.from_wei(balance_wei, 'ether')
        logger.info(f"User {acct.address} balance: {eth_balance} ETH")

        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        # Параметры газа установлены на 0.1 gwei
        gas_price = web3.to_wei(0.1, 'gwei')  # Установлено на 0.1 gwei
        gas_limit = 100000  # Увеличиваем gas limit для успешного выполнения

        deposit_tx = weth_contract.functions.deposit().build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce":   nonce,
            "gas":     gas_limit,
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
            "value": web3.to_wei(amount_eth, "ether"),
            "from":    acct.address  # Добавлено поле "from"
        })
        signed = acct.sign_transaction(deposit_tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        rcpt = web3.eth.wait_for_transaction_receipt(tx_hash, 180)
        if rcpt.status == 1:
            logger.info(f"deposit_eth_to_weth success, ~{amount_eth} ETH -> WETH, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"deposit_eth_to_weth fail, tx={tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("deposit_eth_to_weth except", exc_info=True)
        return False

def get_balances(user: User) -> dict:
    """
    Возвращает балансы ETH, WETH, UJO для указанного пользователя.
    """
    try:
        ua = Web3.to_checksum_address(user.unique_wallet_address)

        raw_eth = web3.eth.get_balance(ua)
        eth_bal = Web3.from_wei(raw_eth, 'ether')

        raw_w = weth_contract.functions.balanceOf(ua).call()
        wdec = weth_contract.functions.decimals().call()
        wbal = raw_w / (10 ** wdec)

        ujo_bal = get_token_balance(ua, ujo_contract)

        return {
            "balances": {
                "eth": float(eth_bal),
                "weth": float(wbal),
                "ujo": float(ujo_bal)
            }
        }
    except Exception as e:
        logger.error(f"get_balances error: {e}", exc_info=True)
        return {"error": "Internal server error."}

def get_token_price_in_usd() -> float:
    """
    Получаем цену UJO в USD (через DexScreener) — если нет ликвидности,
    возвращаем 0.0
    """
    try:
        pair_address = os.environ.get("DEXScreener_PAIR_ADDRESS", "")
        if not pair_address:
            logger.error("DEXScreener_PAIR_ADDRESS не задан.")
            return 0.0

        # Название цепочки для DexScreener. Для сети Base возможно "base".
        chain_name = "base"  # Убедитесь, что это корректное название цепочки для DexScreener
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"DexScreener вернул код={resp.status_code}")
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
        logger.error(f"get_token_price_in_usd except: {e}", exc_info=True)
        return 0.0

def approve_token(user_private_key: str, token_contract, spender: str, amount: int) -> bool:
    """
    Одобрение токенов для расходования контрактом 1inch Router.
    """
    try:
        acct = Account.from_key(user_private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        # Параметры газа установлены на 0.1 gwei
        gas_price = web3.to_wei(0.1, 'gwei')  # Установлено на 0.1 gwei
        gas_limit = 100000  # Стандартный gas limit для approve

        approve_tx = token_contract.functions.approve(
            spender,
            amount
        ).build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce": nonce,
            "gas": gas_limit,
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": web3.to_wei(0.1, 'gwei'),
            "value": 0,
            "from": acct.address  # Добавлено поле "from"
        })
        signed_tx = acct.sign_transaction(approve_tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"approve_token: Одобрено {amount} токенов для {spender}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"approve_token fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("approve_token except", exc_info=True)
        return False

def swap_tokens_via_1inch(user_private_key: str, from_token: str, to_token: str, amount: float) -> bool:
    """
    Выполняет обмен токенов через 1inch, предварительно одобряя необходимые токены.
    """
    try:
        acct = Account.from_key(user_private_key)
        user_address = Web3.to_checksum_address(acct.address)

        # Проверка баланса токенов
        if from_token.upper() == "ETH":
            raw_eth_balance = web3.eth.get_balance(user_address)
            eth_balance = Web3.from_wei(raw_eth_balance, 'ether')
            logger.info(f"ETH Баланс пользователя {user_address}: {eth_balance} ETH")
            if eth_balance < amount:
                logger.error("Недостаточно ETH для обмена.")
                return False
        else:
            from_token_contract = web3.eth.contract(address=Web3.to_checksum_address(from_token), abi=ERC20_ABI)
            decimals = from_token_contract.functions.decimals().call()
            amount_in = int(amount * (10 ** decimals))
            user_balance = from_token_contract.functions.balanceOf(user_address).call()
            user_balance = user_balance / (10 ** decimals)
            logger.info(f"Баланс пользователя {from_token}: {user_balance}")
            if user_balance < amount:
                logger.error(f"Недостаточно {from_token} для обмена.")
                return False

            # Проверка текущего разрешения
            current_allowance = from_token_contract.functions.allowance(user_address, ONEINCH_ROUTER_ADDRESS).call()
            if current_allowance < amount_in:
                logger.info(f"Текущая allowance: {current_allowance}, требуется: {amount_in}. Выполняем approve.")
                approved = approve_token(user_private_key, from_token_contract, ONEINCH_ROUTER_ADDRESS, amount_in)
                if not approved:
                    logger.error("Не удалось одобрить токены для 1inch Router.")
                    return False

        # Получение параметров обмена от 1inch
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ONEINCH_API_KEY}" if ONEINCH_API_KEY else "",
            "Accept": "application/json"
        }

        swap_endpoint = f"{ONEINCH_API_URL}/swap"

        # Формирование запроса с параметрами через URL
        params = {
            "fromTokenAddress": from_token,
            "toTokenAddress": to_token,
            "amount": str(int(amount * (10 ** get_token_decimals(from_token)))),  # Передаем как строку
            "fromAddress": user_address,
            "slippage": "1",  # Допустимое проскальзывание в процентах, передаем как строку
            "disableEstimate": False,
            "allowPartialFill": False
        }

        logger.info(f"Отправка запроса на обмен: {params}")

        response = requests.get(swap_endpoint, params=params, headers=headers)
        logger.info(f"Ответ от 1inch API: статус={response.status_code}, заголовки={response.headers}, тело={response.text}")

        if response.status_code != 200:
            logger.error(f"1inch API вернул код={response.status_code}: {response.text}")
            return False

        try:
            swap_data = response.json()
        except json.JSONDecodeError as jde:
            logger.error(f"Ошибка декодирования JSON: {jde}")
            return False

        if 'tx' not in swap_data:
            logger.error("Не удалось получить данные транзакции от 1inch.")
            return False

        tx = swap_data['tx']

        # Подготовка транзакции
        txn = {
            'from': user_address,
            'to': tx['to'],
            'data': tx['data'],
            'value': int(tx['value']),
            'gas': int(tx['gas']),
            'nonce': web3.eth.get_transaction_count(user_address, 'pending'),  # Добавлен 'pending'
            'chainId': web3.eth.chain_id
        }

        # Проверка наличия полей 'maxFeePerGas' и 'maxPriorityFeePerGas'
        if 'maxFeePerGas' in tx and 'maxPriorityFeePerGas' in tx:
            txn['maxFeePerGas'] = int(tx['maxFeePerGas'])
            txn['maxPriorityFeePerGas'] = int(tx['maxPriorityFeePerGas'])
        elif 'gasPrice' in tx:
            txn['gasPrice'] = int(tx['gasPrice'])
        else:
            logger.error("Не найдены поля gasPrice или maxFeePerGas в ответе 1inch.")
            return False

        logger.info(f"Подготовка транзакции: {txn}")

        # Подписание транзакции
        signed_tx = acct.sign_transaction(txn)

        # Отправка транзакции
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Отправлена транзакция обмена через 1inch, tx_hash={tx_hash.hex()}")

        # Ожидание подтверждения
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"swap_tokens_via_1inch: Успешный обмен, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"swap_tokens_via_1inch fail: {tx_hash.hex()}")
            return False

    except Exception as e:
        logger.error(f"swap_tokens_via_1inch exception: {e}", exc_info=True)
        return False
