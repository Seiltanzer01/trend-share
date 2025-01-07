# staking_logic.py

import os
import logging
from datetime import datetime, timedelta
import requests
import secrets
import string
import sys
import binascii

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

# Адреса контрактов Uniswap V3 для сети Base
UNISWAP_ROUTER_ADDRESS = "0x2626664c2603336E57B271c5C0b26F421741e481"  # SwapRouter02
POOL_FACTORY_ADDRESS = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"      # UniswapV3Factory
QUOTER_V2_ADDRESS = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"        # QuoterV2

# Проверьте, что переменные окружения установлены корректно
required_env_vars = [
    "TOKEN_CONTRACT_ADDRESS",
    "WETH_CONTRACT_ADDRESS",
    "MY_WALLET_ADDRESS",
    "PRIVATE_KEY",
    "DEXScreener_PAIR_ADDRESS"  # Добавлено для функции get_token_price_in_usd
]

missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
if missing_vars:
    logger.error(f"Отсутствуют необходимые переменные окружения: {', '.join(missing_vars)}")
    raise ValueError(f"Отсутствуют необходимые переменные окружения: {', '.join(missing_vars)}")

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

# Uniswap V3 Factory ABI
UNISWAP_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"}
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Uniswap V3 Pool ABI
UNISWAP_POOL_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"name": "", "type": "uint128"}],
        "type": "function"
    }
]

# Uniswap V3 SwapRouter ABI (Полный ABI)
UNISWAP_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct IV3SwapRouter.ExactInputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "bytes", "name": "path", "type": "bytes"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"}
                ],
                "internalType": "struct IV3SwapRouter.ExactInputParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInput",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "stateMutability": "payable",
        "type": "function"
    },
    # Добавьте остальные функции по необходимости
]

# Uniswap V3 Quoter V2 ABI (Полный ABI)
UNISWAP_QUOTER_V2_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "_factory", "type": "address"},
            {"internalType": "address", "name": "_WETH9", "type": "address"}
        ],
        "stateMutability": "nonpayable",
        "type": "constructor"
    },
    {
        "inputs": [],
        "name": "WETH9",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "factory",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "bytes", "name": "path", "type": "bytes"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"}
        ],
        "name": "quoteExactInput",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160[]", "name": "sqrtPriceX96AfterList", "type": "uint160[]"},
            {"internalType": "uint32[]", "name": "initializedTicksCrossedList", "type": "uint32[]"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct IQuoterV2.QuoteExactInputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
            {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "bytes", "name": "path", "type": "bytes"},
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "name": "quoteExactOutput",
        "outputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint160[]", "name": "sqrtPriceX96AfterList", "type": "uint160[]"},
            {"internalType": "uint32[]", "name": "initializedTicksCrossedList", "type": "uint32[]"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct IQuoterV2.QuoteExactOutputSingleParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "quoteExactOutputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
            {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # Добавьте остальные функции QuoterV2 по необходимости
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
    swap_router_contract = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=UNISWAP_ROUTER_ABI)
    pool_factory_contract = web3.eth.contract(address=Web3.to_checksum_address(POOL_FACTORY_ADDRESS), abi=UNISWAP_FACTORY_ABI)
    quoter_contract = web3.eth.contract(address=Web3.to_checksum_address(QUOTER_V2_ADDRESS), abi=UNISWAP_QUOTER_V2_ABI)
except Exception as e:
    logger.error(f"Ошибка инициализации контрактов: {e}", exc_info=True)
    sys.exit(1)

# Определение нескольких fee tiers
FEE_TIERS = [500, 3000, 10000]

def generate_unique_wallet():
    """
    Генерирует уникальный приватный ключ и соответствующий ему адрес кошелька.
    """
    while True:
        unique_wallet_address, unique_private_key = generate_unique_private_key()
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
    Одобрение токенов для расходования контрактом.
    """
    try:
        acct = Account.from_key(user_private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        # Параметры газа установлены на 0.1 gwei
        gas_price = web3.to_wei(0.1, 'gwei')  # Установлено на 0.1 gwei
        gas_limit = 100000  # Стандартный gas limit для approve

        approve_tx = token_contract.functions.approve(
            Web3.to_checksum_address(spender),
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

def get_expected_output(from_token: str, to_token: str, amount_in: int, fee: int) -> int:
    """
    Получает предполагаемый выход токенов через QuoterV2.
    Возвращает amount_out в наименьших единицах токена (например, wei).
    """
    try:
        logger.info(f"Вызов quoteExactInputSingle с параметрами: from_token={from_token}, to_token={to_token}, amount_in={amount_in}, fee={fee}, sqrtPriceLimitX96=0")

        # Создаём структуру параметров как кортеж из пяти элементов
        params = (
            Web3.to_checksum_address(from_token),
            Web3.to_checksum_address(to_token),
            amount_in,
            fee,
            0  # sqrtPriceLimitX96
        )

        # Вызов функции с передачей структуры как кортеж
        result = quoter_contract.functions.quoteExactInputSingle(params).call()

        amount_out = result[0]  # amountOut
        logger.info(f"Полученный quote: {amount_out}")
        return amount_out
    except ContractCustomError as e:
        logger.error(f"ContractCustomError в get_expected_output: {e}")
        return 0
    except ValueError as ve:
        # Попытка извлечь revert reason
        if 'execution reverted' in str(ve):
            error_data = ve.args[0].get('data', '') if hasattr(ve.args[0], 'get') else ''
            if error_data and len(error_data) > 10:
                try:
                    revert_reason = binascii.unhexlify(error_data[10:]).decode('utf-8')
                    logger.error(f"Revert reason: {revert_reason}")
                except Exception:
                    logger.error("Не удалось декодировать revert reason.")
            else:
                logger.error("Нет данных для извлечения revert reason.")
        else:
            logger.error(f"ValueError в get_expected_output: {ve}")
        return 0
    except Exception as e:
        logger.error(f"Ошибка get_expected_output: {e}", exc_info=True)
        return 0

def get_pool_address(from_token: str, to_token: str, fee: int) -> str:
    try:
        pool_address = pool_factory_contract.functions.getPool(
            Web3.to_checksum_address(from_token),
            Web3.to_checksum_address(to_token),
            fee
        ).call()
        if int(pool_address, 16) == 0:
            logger.error(f"Пул не найден для fee tier {fee}.")
            return ""
        logger.info(f"Пул найден для fee tier {fee}: {pool_address}")
        return Web3.to_checksum_address(pool_address)
    except Exception as e:
        logger.error(f"Ошибка get_pool_address: {e}")
        return ""

def check_liquidity(from_token: str, to_token: str, fee: int) -> bool:
    """
    Проверяет наличие ликвидности в пуле Uniswap V3.
    """
    try:
        pool_address = get_pool_address(from_token, to_token, fee)
        if not pool_address:
            logger.error("Пул не найден для указанных токенов и fee tier.")
            return False

        pool_contract = web3.eth.contract(address=pool_address, abi=UNISWAP_POOL_ABI)
        liquidity = pool_contract.functions.liquidity().call()
        logger.info(f"Ликвидность пула (fee tier {fee}): {liquidity}")
        return liquidity > 0
    except Exception as e:
        logger.error(f"Ошибка check_liquidity: {e}")
        return False

def swap_tokens_via_uniswap_v3(user_private_key: str, from_token: str, to_token: str, amount: float) -> bool:
    """
    Выполняет обмен токенов через Uniswap V3 с поддержкой нескольких fee tiers.
    """
    try:
        acct = Account.from_key(user_private_key)
        user_address = Web3.to_checksum_address(acct.address)

        # Проверка баланса ETH
        raw_eth_balance = web3.eth.get_balance(user_address)
        eth_balance = Web3.from_wei(raw_eth_balance, 'ether')
        logger.info(f"ETH Баланс пользователя {user_address}: {eth_balance} ETH")

        from_token_contract = web3.eth.contract(address=Web3.to_checksum_address(from_token), abi=ERC20_ABI)
        decimals = from_token_contract.functions.decimals().call()
        amount_in = int(amount * (10 ** decimals))

        logger.info(f"Пытаемся обменять {amount} токенов {from_token} на {to_token}")

        gas_price = web3.to_wei(0.1, 'gwei')  # Определение gas_price

        for fee in FEE_TIERS:
            logger.info(f"Проверяем пул с fee tier {fee}...")
            if not check_liquidity(from_token, to_token, fee):
                logger.warning(f"Пул с fee tier {fee} не имеет достаточной ликвидности.")
                continue

            # Получаем предполагаемый выход токенов
            expected_output = get_expected_output(from_token, to_token, amount_in, fee)
            if expected_output == 0:
                logger.warning(f"Не удалось получить ожидаемый выход для fee tier {fee}. Пробуем следующий.")
                continue

            slippage_tolerance = 0.12  # 12%
            amount_out_minimum = int(expected_output * (1 - slippage_tolerance))
            if amount_out_minimum < 1234:
                amount_out_minimum = 1234  # Установлено на 1234 вместо 1
            logger.info(f"Предполагаемый выход: {expected_output / (10 ** get_token_decimals(to_token))} токенов, минимально допустимый: {amount_out_minimum}")

            # Проверка allowance и его установка при необходимости
            allowance = from_token_contract.functions.allowance(user_address, UNISWAP_ROUTER_ADDRESS).call()
            logger.info(f"Текущий allowance: {allowance}, необходимый: {amount_in}")
            if allowance < amount_in:
                logger.info("Недостаточный allowance. Выполняем одобрение.")
                if not approve_token(user_private_key, from_token_contract, UNISWAP_ROUTER_ADDRESS, amount_in):
                    logger.error("Ошибка при одобрении токенов.")
                    continue  # Пробуем следующий fee tier

            # Определение параметров для транзакции как кортеж
            params = (
                Web3.to_checksum_address(from_token),
                Web3.to_checksum_address(to_token),
                amount_in,
                fee,
                0  # sqrtPriceLimitX96
            )

            # Строим транзакцию с точной оценкой газа
            try:
                gas_estimate = quoter_contract.functions.quoteExactInputSingle(params).estimateGas({
                    "from": user_address,
                    "value": 0
                })
                logger.info(f"Оценка газа для транзакции: {gas_estimate}")
            except Exception as e:
                logger.error(f"Ошибка при оценке газа: {e}")
                continue

            # Проверяем, хватает ли ETH для оплаты газа
            gas_cost_eth = Web3.from_wei(gas_price * gas_estimate, 'ether')
            logger.info(f"Ожидаемая стоимость газа: {gas_cost_eth} ETH")
            if eth_balance < gas_cost_eth:
                logger.error(f"Недостаточно ETH для оплаты газа. Требуется: ~{gas_cost_eth} ETH, доступно: {eth_balance} ETH")
                return False

            # Строим транзакцию
            swap_tx = swap_router_contract.functions.exactInputSingle(
                Web3.to_checksum_address(from_token),
                Web3.to_checksum_address(to_token),
                fee,
                Web3.to_checksum_address(user_address),
                int(datetime.utcnow().timestamp()) + 600,  # 10 минут deadline
                amount_in,
                amount_out_minimum,
                0  # Без ограничения цены
            ).build_transaction({
                "chainId": web3.eth.chain_id,
                "nonce": web3.eth.get_transaction_count(user_address, 'pending'),
                "gas": gas_estimate,
                "maxFeePerGas": gas_price,  # Установлено на 0.1 gwei
                "maxPriorityFeePerGas": gas_price,  # Установлено на 0.1 gwei
                "value": 0,
                "from": user_address  # Добавлено поле "from"
            })

            # Подписываем транзакцию
            signed_tx = acct.sign_transaction(swap_tx)

            # Отправляем транзакцию
            try:
                tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                logger.info(f"Отправлена транзакция обмена, tx_hash={tx_hash.hex()}")
                receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
                if receipt.status == 1:
                    logger.info(f"swap_tokens_via_uniswap_v3: Успешный обмен, tx={tx_hash.hex()}")
                    return True
                else:
                    logger.error(f"swap_tokens_via_uniswap_v3 fail: {tx_hash.hex()}")
                    continue  # Переходим к следующему fee tier
            except ValueError as e:
                if "replacement transaction underpriced" in str(e):
                    logger.warning("Замена транзакции. Увеличиваем gas price.")
                    # В данном случае, мы уже установили фиксированную стоимость газа, поэтому продолжаем
                    continue
                else:
                    logger.error(f"Ошибка при отправке транзакции: {e}", exc_info=True)
                    continue  # Переходим к следующему fee tier
            except Exception as e:
                logger.error(f"Ошибка при отправке транзакции: {e}", exc_info=True)
                continue  # Переходим к следующему fee tier
    except Exception as e:
        logger.error(f"swap_tokens_via_uniswap_v3 exception: {e}", exc_info=True)
        return False

    logger.error("swap_tokens_via_uniswap_v3: Не удалось выполнить обмен ни с одним fee tier.")
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
            logger.error(f"Транзакция не подтверждена или не найдена: {tx_hash}")
            return False

        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        price_usd = get_token_price_in_usd()
        if price_usd <= 0:
            logger.error("Не удалось получить цену токена в USD.")
            return False

        found = None
        for lg in r.logs:
            if lg.address.lower() == token_contract.address.lower():
                if len(lg.topics) >= 3:
                    if lg.topics[0].hex().lower() == transfer_topic.lower():
                        from_addr = "0x" + lg.topics[1].hex()[26:]
                        to_addr = "0x" + lg.topics[2].hex()[26:]
                        from_addr = Web3.to_checksum_address(from_addr)
                        to_addr = Web3.to_checksum_address(to_addr)

                        # Смотрим, что user.unique_wallet_address -> PROJECT_WALLET_ADDRESS
                        if (from_addr.lower() == user.unique_wallet_address.lower()
                                and to_addr.lower() == PROJECT_WALLET_ADDRESS.lower()):
                            amt_int = int(lg.data, 16)
                            token_amt = amt_int / (10 ** 18)
                            usd_amt = token_amt * price_usd
                            logger.info(f"Транзакция {tx_hash}: {token_amt} токенов, стоимость {usd_amt} USD")
                            if usd_amt >= 25:
                                found = {
                                    "token_amount": token_amt,
                                    "usd_amount": usd_amt
                                }
                                break
        if not found:
            logger.error(f"Транзакция {tx_hash} не соответствует критериям стейкинга.")
            return False

        # Проверка на дублирующийся tx_hash
        ex = UserStaking.query.filter_by(tx_hash=tx_hash).first()
        if ex:
            logger.warning(f"Транзакция {tx_hash} уже существует в базе.")
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
    except Exception as e:
        logger.error(f"confirm_staking_tx({tx_hash}) except: {e}", exc_info=True)
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
        logger.info("accumulate_staking_rewards: Награды успешно добавлены.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"accumulate_staking_rewards except: {e}", exc_info=True)
