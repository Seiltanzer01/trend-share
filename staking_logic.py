# staking_logic.py

import os
import logging
import traceback
from datetime import datetime, timedelta
import requests
import secrets
import string
import json
import hashlib  # Для генерации unique_id

from web3.exceptions import ContractCustomError  # Для корректной обработки исключений
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_structured_data

from models import db, User, UserStaking

logger = logging.getLogger(__name__)

# Подключение к RPC (например, Base)
INFURA_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID")
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Адреса контрактов
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS", "0xYOUR_TOKEN_CONTRACT_ADDRESS")  # UJO
WETH_CONTRACT_ADDRESS  = os.environ.get("WETH_CONTRACT_ADDRESS",  "0xYOUR_WETH_CONTRACT_ADDRESS")  # WETH
UJO_CONTRACT_ADDRESS   = TOKEN_CONTRACT_ADDRESS  # Если UJO — это тот же токен
PROJECT_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS",      "0xYOUR_PROJECT_WALLET_ADDRESS")
PERMIT2_CONTRACT_ADDRESS = "0x000000000022d473030f116ddee9f6b43ac78ba3"  # Пример адреса Permit2
SWAP_CONTRACT_ADDRESS = "0xbc3c5ca50b6a215edf00815965485527f26f5da8"  # Пример адреса 0x Swap v2

# Проверка наличия необходимых переменных окружения
if (
    TOKEN_CONTRACT_ADDRESS == "0xYOUR_TOKEN_CONTRACT_ADDRESS"
    or WETH_CONTRACT_ADDRESS  == "0xYOUR_WETH_CONTRACT_ADDRESS"
    or PROJECT_WALLET_ADDRESS == "0xYOUR_PROJECT_WALLET_ADDRESS"
):
    logger.error("Одна или несколько ENV-переменных (TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS) не заданы.")
    raise ValueError("Некорректные ENV для TOKEN_CONTRACT_ADDRESS/WETH_CONTRACT_ADDRESS/MY_WALLET_ADDRESS.")

# ERC20 ABI с необходимыми методами
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

# Permit2 ABI (Минимальный для permitTransferFrom)
PERMIT2_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "expiration", "type": "uint256"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"}
        ],
        "name": "permitTransferFrom",
        "outputs": [],
        "type": "function",
    }
]

# SWAP_CONTRACT_ABI: Используем минимальный ABI для метода execute
SWAP_CONTRACT_ABI = [
    {
        "constant": False,
        "inputs": [
            {
                "internalType": "tuple",
                "name": "allowedSlippage",
                "type": "tuple",
                "components": [
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "address", "name": "buyToken", "type": "address"},
                    {"internalType": "uint256", "name": "minAmountOut", "type": "uint256"}
                ]
            },
            {
                "internalType": "bytes[]",
                "name": "actions",
                "type": "bytes[]"
            },
            {
                "internalType": "bytes32",
                "name": "uniqueId",
                "type": "bytes32"
            }
        ],
        "name": "execute",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Проверка корректности адресов
if not Web3.is_address(TOKEN_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный TOKEN_CONTRACT_ADDRESS: {TOKEN_CONTRACT_ADDRESS}")
if not Web3.is_address(WETH_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный WETH_CONTRACT_ADDRESS: {WETH_CONTRACT_ADDRESS}")
if not Web3.is_address(UJO_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный UJO_CONTRACT_ADDRESS: {UJO_CONTRACT_ADDRESS}")
if not Web3.is_address(PROJECT_WALLET_ADDRESS):
    raise ValueError(f"Некорректный PROJECT_WALLET_ADDRESS: {PROJECT_WALLET_ADDRESS}")
if not Web3.is_address(PERMIT2_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный PERMIT2_CONTRACT_ADDRESS: {PERMIT2_CONTRACT_ADDRESS}")
if not Web3.is_address(SWAP_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный SWAP_CONTRACT_ADDRESS: {SWAP_CONTRACT_ADDRESS}")

# Создаём объекты контрактов
token_contract = web3.eth.contract(
    address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)
weth_contract = web3.eth.contract(
    address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS),
    abi=ERC20_ABI  # Используем ERC20 ABI для WETH
)
ujo_contract  = web3.eth.contract(
    address=Web3.to_checksum_address(UJO_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)
permit2_contract = web3.eth.contract(
    address=Web3.to_checksum_address(PERMIT2_CONTRACT_ADDRESS),
    abi=PERMIT2_ABI
)
swap_contract = web3.eth.contract(
    address=Web3.to_checksum_address(SWAP_CONTRACT_ADDRESS),
    abi=SWAP_CONTRACT_ABI
)

# 0x Swap v2 (permit2)
ZEROX_API_KEY = os.environ.get("ZEROX_API_KEY", "")
DEFAULT_0X_HEADERS = {
    "0x-api-key": ZEROX_API_KEY,
    "0x-version": "v2",
}

def generate_unique_wallet():
    """
    Генерирует уникальный приватный ключ и соответствующий ему адрес кошелька.
    """
    while True:
        private_key = generate_unique_private_key()
        acct = Account.from_key(private_key)
        unique_wallet_address = Web3.to_checksum_address(acct.address)
        if not User.query.filter_by(unique_wallet_address=unique_wallet_address).first():
            return unique_wallet_address, private_key

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
        return raw / (10 ** dec)
    except:
        logger.error("get_token_balance error", exc_info=True)
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

        base_gas_price = web3.eth.gas_price
        maxFeePerGas = base_gas_price * 2  # Увеличиваем gas price для большей вероятности включения в блок
        maxPriorityFeePerGas = Web3.to_wei(2, 'gwei')  # Увеличиваем приоритетную комиссию

        tx = token_contract.functions.transfer(
            Web3.to_checksum_address(to_address),
            amt_wei
        ).build_transaction({
            "chainId":  web3.eth.chain_id,
            "nonce":    web3.eth.get_transaction_count(acct.address, 'pending'),
            "gas":      100000,  # Увеличиваем gas limit для успешного выполнения
            "maxFeePerGas": int(maxFeePerGas),
            "maxPriorityFeePerGas": int(maxPriorityFeePerGas),
            "value": 0
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
        if "replacement transaction underpriced" in str(e):
            logger.warning("Ошибка замены транзакции, увеличиваем gas price.")
            base_gas_price *= 1.1
            maxPriorityFeePerGas *= 1.1
            return send_token_reward(to_address, amount, from_address, private_key)
        logger.error("send_token_reward except", exc_info=True)
        return False

def send_eth(to_address: str, amount_eth: float, private_key: str) -> bool:
    """
    Отправка нативного ETH (для gas и т.п.) с увеличенной комиссией.
    """
    try:
        acct = Account.from_key(private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        priority_wei = Web3.to_wei(2, 'gwei')  # Увеличиваем приоритетную комиссию
        max_fee_wei  = Web3.to_wei(50, 'gwei')  # Увеличиваем общую комиссию

        tx = {
            "nonce": nonce,
            "to": Web3.to_checksum_address(to_address),
            "value": web3.to_wei(amount_eth, 'ether'),
            "chainId": web3.eth.chain_id,
            "maxFeePerGas": int(max_fee_wei),
            "maxPriorityFeePerGas": int(priority_wei),
            "gas": 21000  # Стандартный gas limit для ETH
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
    except:
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

        priority_wei = Web3.to_wei(2, 'gwei')  # Увеличиваем приоритетную комиссию
        max_fee_wei  = Web3.to_wei(50, 'gwei')  # Увеличиваем общую комиссию

        deposit_tx = weth_contract.functions.deposit().build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce":   nonce,
            "maxFeePerGas": max_fee_wei,
            "maxPriorityFeePerGas": priority_wei,
            "gas": 100000,  # Увеличиваем gas limit для успешного выполнения
            "value": web3.to_wei(amount_eth, "ether"),
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
    except:
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

        wdec = weth_contract.functions.decimals().call()
        raw_w = weth_contract.functions.balanceOf(ua).call()
        wbal = raw_w / (10 ** wdec)

        ujo_bal = get_token_balance(ua, ujo_contract)

        return {
            "balances": {
                "eth": float(eth_bal),
                "weth": float(wbal),
                "ujo": float(ujo_bal)
            }
        }
    except:
        logger.error("get_balances error", exc_info=True)
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

        chain_name = "base"  # Уточните название цепочки для DexScreener
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"DexScreener вернул код={resp.status_code}")
            return 0.0

        data = resp.json()
        pair = data.get("pair", {})
        if not pair:
            return 0.0

        return float(pair.get("priceUsd", "0"))
    except:
        logger.error("get_token_price_in_usd except", exc_info=True)
        return 0.0

# --- 0x Swap v2 (permit2) ---

def get_0x_quote(
    sell_token: str,
    buy_token: str,
    sell_amount: int,
    taker_address: str,
    chain_id: int = 8453
) -> dict:
    """
    Получаем котировку 0x permit2 (v2) для сети Base.
    """
    if not ZEROX_API_KEY:
        logger.error("ZEROX_API_KEY отсутствует.")
        return {}

    # Проверка параметров
    if not Web3.is_address(sell_token) or not Web3.is_address(buy_token):
        logger.error("Некорректные адреса sell_token или buy_token.")
        return {}
    if sell_amount <= 0:
        logger.error("sell_amount должно быть положительным.")
        return {}

    url = "https://api.0x.org/swap/permit2/quote"
    params = {
        "chainId": chain_id,
        "sellToken": sell_token,
        "buyToken": buy_token,
        "sellAmount": str(sell_amount),
        "taker": taker_address,
    }

    try:
        resp = requests.get(url, params=params, headers=DEFAULT_0X_HEADERS, timeout=20)
        if resp.status_code != 200:
            logger.error(f"Ошибка 0x API: {resp.status_code}, текст: {resp.text}")
            return {}

        data = resp.json()
        if "transaction" not in data:
            logger.error("Ответ 0x API не содержит поля 'transaction'.")
            return {}

        return data
    except Exception as e:
        logger.error(f"Ошибка при вызове 0x API: {e}", exc_info=True)
        return {}

def sign_permit2(user_private_key: str, permit_data: dict) -> dict:
    """
    Подписывает Permit2 сообщение согласно EIP712.
    Возвращает подпись в формате r, s, v.
    """
    try:
        # Используем eth_account для создания структурированного сообщения
        message = {
            "types": permit_data["eip712"]["types"],
            "domain": permit_data["eip712"]["domain"],
            "primaryType": permit_data["eip712"]["primaryType"],
            "message": permit_data["eip712"]["message"]
        }

        # Преобразование полей из строк в целые числа
        message["message"]["permitted"]["amount"] = int(message["message"]["permitted"]["amount"])
        message["message"]["nonce"] = int(message["message"]["nonce"])
        message["message"]["deadline"] = int(message["message"]["deadline"])

        # Создаем EIP712 сообщение
        signed_message = Account.sign_message(
            encode_structured_data(message),
            private_key=user_private_key
        )

        # Преобразуем r и s в hex строки
        r_hex = '0x' + format(signed_message.r, '064x')
        s_hex = '0x' + format(signed_message.s, '064x')

        # Возвращаем r, s, v
        return {
            "v": signed_message.v,
            "r": r_hex,
            "s": s_hex
        }
    except Exception as e:
        logger.error(f"Ошибка подписания Permit2: {e}", exc_info=True)
        return {}

def decode_too_much_slippage(error_data: str) -> str:
    """
    Декодирует ошибку TooMuchSlippage(address,uint256,uint256).

    :param error_data: Hex строка с данными ошибки.
    :return: Строка с декодированной информацией об ошибке.
    """
    try:
        if error_data.startswith('0x'):
            error_data = error_data[2:]
        
        # Проверяем, начинается ли ошибка с сигнатуры TooMuchSlippage
        # Сигнатура ошибки: keccak256("TooMuchSlippage(address,uint256,uint256)")[:4] = 0x4be6321b
        if not error_data.startswith('4be6321b'):
            return "Неизвестная ошибка контракта."
        
        # Удаляем сигнатуру ошибки
        data = error_data[8:]
        
        # Каждое поле занимает 64 символа (32 байта) в hex представлении
        token_hex = data[0:64]
        expected_hex = data[64:128]
        actual_hex = data[128:192]
        
        # Преобразуем значения
        token_address = '0x' + token_hex[-40:]  # Последние 40 символов представляют адрес
        expected = int(expected_hex, 16)
        actual = int(actual_hex, 16)
        
        return f"Ошибка контракта: TooMuchSlippage(token={token_address}, expected={expected}, actual={actual})"
    
    except Exception as e:
        logger.error(f"Ошибка декодирования TooMuchSlippage: {e}", exc_info=True)
        return "Ошибка декодирования ошибки контракта."

def decode_contract_error(error_data: str) -> str:
    """
    Декодирует ошибку контракта по предоставленным данным.

    :param error_data: Hex строка с данными ошибки.
    :return: Строка с декодированной информацией об ошибке.
    """
    try:
        if error_data.startswith('0x'):
            error_data = error_data[2:]
        
        # Проверяем тип ошибки по сигнатуре
        error_signature = error_data[:8]
        
        if error_signature == "4be6321b":
            # Это TooMuchSlippage(address,uint256,uint256)
            return decode_too_much_slippage("0x" + error_data)
        else:
            # Неизвестная ошибка
            return "Не удалось декодировать ошибку контракта."
    
    except Exception as e:
        logger.error(f"Ошибка декодирования ошибки контракта: {e}", exc_info=True)
        return f"Ошибка декодирования: {e}"

def execute_swap(quote_json: dict, private_key: str, user: User) -> bool:
    """
    Выполняет транзакцию обмена (swap) 0x permit2 v2 с использованием подписанного Permit2.
    """
    if not quote_json:
        logger.error("Пустой quote_json.")
        return False

    try:
        # Логирование полного quote_json
        logger.info(f"Полный quote_json: {json.dumps(quote_json, indent=2)}")
    except Exception as e:
        logger.error(f"Ошибка логирования quote_json: {e}", exc_info=True)

    tx_obj = quote_json.get("transaction", {})
    if not isinstance(tx_obj, dict):
        logger.error("Поле 'transaction' в quote_json отсутствует или не является словарем.")
        return False

    # Извлечение параметров транзакции
    try:
        to_addr = Web3.to_checksum_address(tx_obj.get("to"))
    except Exception as e:
        logger.error(f"Некорректный адрес назначения: {tx_obj.get('to')}")
        return False

    data_hex = tx_obj.get("data")
    val_str = tx_obj.get("value", "0")
    gas_limit_str = tx_obj.get("gas", None)

    if not to_addr or not data_hex:
        logger.error("Недостаточно данных для транзакции (нет 'to' или 'data').")
        return False

    try:
        value = int(val_str)
    except ValueError:
        logger.error("Ошибка преобразования 'value' в int.")
        return False

    # Преобразование gas_limit из строки в int
    if gas_limit_str is not None:
        try:
            gas_limit = int(gas_limit_str)
        except ValueError:
            logger.error("Некорректное значение 'gas' в quote_json.")
            return False
    else:
        gas_limit = 21000  # Значение по умолчанию

    acct = Account.from_key(private_key)
    nonce = web3.eth.get_transaction_count(acct.address, 'pending')

    # Извлечение spender и sell_token
    try:
        # Используем spender из permit2 сообщения
        permit_data = quote_json.get("permit2", {})
        if not permit_data:
            logger.error("Permit2 данные отсутствуют в quote_json.")
            return False

        spender = Web3.to_checksum_address(permit_data["eip712"]["message"]["spender"])
        sell_token = Web3.to_checksum_address(quote_json.get("sellToken"))
    except Exception as e:
        logger.error(f"Некорректный адрес sell_token или spender: {e}")
        return False

    sell_amount = int(quote_json.get("sellAmount", "0"))
    try:
        allowance = token_contract.functions.allowance(acct.address, spender).call()
        logger.info(f"Текущее allowance для {spender}: {allowance}")
    except Exception as e:
        logger.error(f"Ошибка вызова allowance: {e}")
        return False

    if allowance < sell_amount:
        logger.info(f"Недостаточно allowance: {allowance}. Используем Permit2 для установки нового allowance.")
        # Получаем Permit2 данные из quote_json

        # Подписываем Permit2 сообщение
        signature = sign_permit2(private_key, permit_data)
        if not signature:
            logger.error("Не удалось подписать Permit2.")
            return False

        # Создаем действие для Permit2
        try:
            permit_action = permit2_contract.encodeABI(
                fn_name="permitTransferFrom",
                args=[
                    Web3.to_checksum_address(permit_data["eip712"]["message"]["permitted"]["token"]),
                    acct.address,
                    spender,
                    int(permit_data["eip712"]["message"]["permitted"]["amount"]),
                    int(permit_data["eip712"]["message"]["deadline"]),
                    signature["v"],
                    signature["r"],
                    signature["s"]
                ]
            )
        except Exception as e:
            logger.error(f"Ошибка кодирования permitTransferFrom: {e}", exc_info=True)
            return False

        # Добавляем permit_action и data_hex
        actions_encoded = [permit_action, data_hex]

        # Кодируем массив действий в bytes[]
        try:
            actions_serialized = [bytes.fromhex(action[2:]) for action in actions_encoded]
        except Exception as e:
            logger.error(f"Ошибка сериализации действий: {e}", exc_info=True)
            return False

        # Получаем AllowedSlippage из quote_json с увеличенным сдвигом
        try:
            # Увеличиваем допустимый сдвиг до 2%
            slippage_percentage = 0.02  # 2%
            min_amount_out = int(float(quote_json.get("minBuyAmount", "0")) * (1 - slippage_percentage))
            allowed_slippage = {
                "recipient": Web3.to_checksum_address(user.unique_wallet_address),
                "buyToken": Web3.to_checksum_address(quote_json.get("buyToken")),
                "minAmountOut": min_amount_out
            }
        except Exception as e:
            logger.error(f"Ошибка получения AllowedSlippage: {e}", exc_info=True)
            return False

        # Создаем структуру AllowedSlippage
        AllowedSlippage = (
            allowed_slippage["recipient"],
            allowed_slippage["buyToken"],
            allowed_slippage["minAmountOut"]
        )

        # Генерация уникального bytes32 идентификатора (опционально)
        unique_id = hashlib.sha256(nonce.to_bytes(32, byteorder='big')).hexdigest()[:64]

        # Кодируем функцию 'execute' с новыми параметрами
        try:
            execute_data = swap_contract.encodeABI(
                fn_name="execute",
                args=[
                    AllowedSlippage,
                    actions_serialized,
                    "0x" + unique_id  # Уникальный идентификатор вместо нулей
                ]
            )
        except Exception as e:
            logger.error(f"Ошибка кодирования execute: {e}", exc_info=True)
            return False

        # Обновляем данные транзакции
        data_hex = execute_data

        # Логируем обновленные данные транзакции
        logger.info(f"Обновленные данные транзакции с Permit2: {data_hex}")

    # Проверка баланса отправителя
    sender_balance = web3.eth.get_balance(acct.address)
    gas_price = int(web3.eth.gas_price)  # Убедитесь, что gas_price является int

    required_amount = value + gas_price * gas_limit
    logger.info(f"Баланс отправителя: {sender_balance}, необходимая сумма: {required_amount}")
    if sender_balance < required_amount:
        logger.error(
            f"Недостаточно средств для выполнения транзакции. Баланс: {sender_balance}, "
            f"необходимая сумма: {required_amount}"
        )
        return False

    # Оценка газа с декодированием ошибки
    try:
        estimated_gas = web3.eth.estimate_gas({
            "from": acct.address,
            "to": to_addr,
            "data": data_hex,
            "value": value,
        })
        logger.info(f"Оценка газа: {estimated_gas}")
    except ContractCustomError as e:
        decoded_error = decode_contract_error(e.args[0])
        logger.error(f"Ошибка при оценке газа: {decoded_error}")
        return False
    except Exception as e:
        logger.error(f"Не удалось оценить газ: {e}", exc_info=True)
        return False

    # Если gas_limit меньше оцененного, используйте оцененное значение
    if gas_limit < estimated_gas:
        gas_limit = estimated_gas
        logger.info(f"Используется оцененное значение газа: {gas_limit}")

    logger.info(f"Установлен gas_limit: {gas_limit}")

    # Устанавливаем параметры газа
    try:
        maxPriorityFeePerGas = min(Web3.to_wei(5, 'gwei'), gas_price // 2)  # Увеличиваем приоритетную комиссию до 5 gwei
        maxFeePerGas = gas_price + maxPriorityFeePerGas
    except Exception as e:
        logger.error(f"Ошибка расчёта газа: {e}", exc_info=True)
        return False

    tx = {
        "chainId": web3.eth.chain_id,
        "nonce": nonce,
        "to": to_addr,
        "data": data_hex,
        "value": value,
        "gas": gas_limit,
        "maxFeePerGas": int(maxFeePerGas),
        "maxPriorityFeePerGas": int(maxPriorityFeePerGas),
    }

    try:
        signed_tx = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        if receipt.status == 1:
            logger.info(f"Транзакция выполнена успешно, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"Транзакция завершилась с ошибкой, tx={tx_hash.hex()}")
            return False
    except ContractCustomError as e:
        decoded_error = decode_contract_error(e.args[0])
        logger.error(f"Contract error: {decoded_error}")
        return False
    except Exception as e:
        logger.error(f"Ошибка выполнения транзакции: {e}", exc_info=True)
        return False

def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """
    Если транзакция >=25$ => создаём запись в UserStaking + assistant_premium = True.
    """
    if not user or not user.unique_wallet_address or not tx_hash:
        return False
    try:
        r = web3.eth.get_transaction_receipt(tx_hash)
        if not r or r.status != 1:
            return False

        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        price_usd      = get_token_price_in_usd()
        if price_usd <= 0:
            return False

        found = None
        for lg in r.logs:
            if lg.address.lower() == token_contract.address.lower():
                if len(lg.topics) >= 3:
                    if lg.topics[0].hex().lower() == transfer_topic.lower():
                        from_addr = "0x" + lg.topics[1].hex()[26:]
                        to_addr   = "0x" + lg.topics[2].hex()[26:]
                        from_addr = Web3.to_checksum_address(from_addr)
                        to_addr   = Web3.to_checksum_address(to_addr)

                        # Смотрим, что user.unique_wallet_address -> PROJECT_WALLET_ADDRESS
                        if (from_addr.lower() == user.unique_wallet_address.lower()
                                and to_addr.lower() == PROJECT_WALLET_ADDRESS.lower()):
                            amt_int   = int(lg.data, 16)
                            token_amt = amt_int / (10 ** 18)
                            usd_amt   = token_amt * price_usd
                            if usd_amt >= 25:
                                found = {
                                    "token_amount": token_amt,
                                    "usd_amount": usd_amt
                                }
                                break
        if not found:
            return False

        # Проверка на дублирующийся tx_hash
        ex = UserStaking.query.filter_by(tx_hash=tx_hash).first()
        if ex:
            return False

        new_s = UserStaking(
            user_id=user.id,
            tx_hash=tx_hash,
            staked_usd=found["usd_amount"],
            staked_amount=found["token_amount"],
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow() + timedelta(days=30),
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_s)
        user.assistant_premium = True
        db.session.commit()
        logger.info(f"User {user.id} застейкал ~{found['usd_amount']:.2f}$ (tx={tx_hash}). Premium on.")
        return True
    except:
        logger.error(f"confirm_staking_tx({tx_hash}) except", exc_info=True)
        db.session.rollback()
        return False

def accumulate_staking_rewards():
    """
    Пример: раз в неделю добавляем всем, у кого staked_amount>0, +0.5 UJO к pending_rewards.
    """
    try:
        st = UserStaking.query.all()
        for s in st:
            if s.staked_amount > 0:
                s.pending_rewards += 0.5
        db.session.commit()
    except:
        db.session.rollback()
        logger.error("accumulate_staking_rewards except", exc_info=True)

# --- Новые функции для работы с 0x API Swap ---

def initiate_swap(user: User, sell_token: str, buy_token: str, sell_amount: float) -> bool:
    """
    Инициирует процесс свапа: получает котировку, подписывает Permit2 и выполняет транзакцию.
    """
    try:
        # Получаем цену токена
        price_usd = get_token_price_in_usd()
        if price_usd <= 0:
            logger.error("Не удалось получить цену токена UJO.")
            return False

        # Конвертируем sell_amount в базовые единицы (wei)
        sell_amount_wei = int(sell_amount * (10 ** token_contract.functions.decimals().call()))

        # Получаем котировку от 0x API
        quote = get_0x_quote(
            sell_token=sell_token,
            buy_token=buy_token,
            sell_amount=sell_amount_wei,
            taker_address=user.unique_wallet_address
        )
        if not quote:
            logger.error("Не удалось получить котировку от 0x API.")
            return False

        # Выполняем свап
        success = execute_swap(quote, user.unique_private_key, user)
        if success:
            logger.info(f"Свап успешно выполнен для пользователя {user.id}.")
            return True
        else:
            logger.error(f"Свап не удался для пользователя {user.id}.")
            return False
    except Exception as e:
        logger.error(f"Ошибка в initiate_swap: {e}", exc_info=True)
        return False

def handle_swap_request(user: User, sell_token: str, buy_token: str, sell_amount: float) -> dict:
    """
    Обрабатывает запрос на свап от пользователя.
    """
    if not verify_private_key(user):
        return {"error": "Invalid private key."}

    # Инициируем свап
    if initiate_swap(user, sell_token, buy_token, sell_amount):
        return {"status": "success", "message": "Swap executed successfully."}
    else:
        return {"error": "Swap failed."}

# Пример маршрута Flask для обработки свапов
from flask import Blueprint, request, jsonify, session
from flask_wtf.csrf import CSRFError

swap_bp = Blueprint('swap', __name__)

@swap_bp.route('/api/swap', methods=['POST'])
def swap_route():
    try:
        csrf_token = request.headers.get('X-CSRFToken')
        if not csrf_token:
            return jsonify({"error": "CSRF token missing."}), 400
        validate_csrf(csrf_token)

        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user = User.query.get(session['user_id'])
        if not user or not user.unique_wallet_address or not user.unique_private_key:
            return jsonify({"error": "User not found or wallet not set."}), 400

        data = request.get_json() or {}
        sell_token = data.get("sell_token")
        buy_token = data.get("buy_token")
        sell_amount = data.get("sell_amount")

        if not sell_token or not buy_token or not sell_amount:
            return jsonify({"error": "Missing parameters."}), 400

        try:
            sell_amount = float(sell_amount)
            if sell_amount <= 0:
                raise ValueError
        except:
            return jsonify({"error": "Invalid sell_amount."}), 400

        result = handle_swap_request(user, sell_token, buy_token, sell_amount)
        if "error" in result:
            return jsonify(result), 400
        else:
            return jsonify(result), 200

    except CSRFError:
        return jsonify({"error": "CSRF token missing or invalid."}), 400
    except Exception as e:
        logger.error("swap_route exception", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

# --- Конец файла staking_logic.py ---
