# staking_logic.py

import os
import logging
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
UNISWAP_ROUTER_ADDRESS  = os.environ.get("UNISWAP_ROUTER_ADDRESS", "0x2626664c2603336E57B271c5C0b26F421741e481")  # Uniswap v3 SwapRouter

# Проверка наличия необходимых переменных окружения
if (
    TOKEN_CONTRACT_ADDRESS == "0xYOUR_TOKEN_CONTRACT_ADDRESS"
    or WETH_CONTRACT_ADDRESS  == "0xYOUR_WETH_CONTRACT_ADDRESS"
    or PROJECT_WALLET_ADDRESS == "0xYOUR_PROJECT_WALLET_ADDRESS"
    or UNISWAP_ROUTER_ADDRESS == "0x2626664c2603336E57B271c5C0b26F421741e481"  # Предполагаемый адрес
):
    logger.error("Одна или несколько ENV-переменных (TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS, UNISWAP_ROUTER_ADDRESS) не заданы.")
    raise ValueError("Некорректные ENV для TOKEN_CONTRACT_ADDRESS/WETH_CONTRACT_ADDRESS/MY_WALLET_ADDRESS/UNISWAP_ROUTER_ADDRESS.")

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

# Дополнительные методы для WETH
WETH_ABI = ERC20_ABI + [
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
]

# Uniswap v3 SwapRouter ABI (Минимальный для exactInputSingle)
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
                "internalType": "struct ISwapRouter.ExactInputSingleParams",
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
    }
]

# SwapRouter контракт
swap_router_contract = web3.eth.contract(
    address=Web3.to_checksum_address(UNISWAP_ROUTER_ADDRESS),
    abi=UNISWAP_ROUTER_ABI
)

# Создаём объекты контрактов
token_contract = web3.eth.contract(
    address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)
weth_contract = web3.eth.contract(
    address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS),
    abi=WETH_ABI
)
ujo_contract  = web3.eth.contract(
    address=Web3.to_checksum_address(UJO_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)

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
            try:
                base_gas_price = web3.eth.gas_price * 1.1
                maxPriorityFeePerGas = int(Web3.to_wei(2.2, 'gwei'))
                # Рекурсивный вызов с увеличенным gas_price
                return send_token_reward(to_address, amount, from_address, private_key)
            except Exception as inner_e:
                logger.error(f"Ошибка при повторной попытке send_token_reward: {inner_e}", exc_info=True)
                return False
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
            "maxFeePerGas": max_fee_wei,
            "maxPriorityFeePerGas": priority_wei,
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

        # Уточните название цепочки для DexScreener. Например, для Base может быть 'base' или другое.
        chain_name = "base"  # Замените на корректное название цепочки согласно DexScreener
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

        approve_tx = token_contract.functions.approve(
            Web3.to_checksum_address(spender),
            amount
        ).build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce": nonce,
            "gas": 100000,
            "gasPrice": web3.to_wei('50', 'gwei'),
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

def swap_tokens_via_uniswap_v3(user_private_key: str, from_token: str, to_token: str, amount: float) -> bool:
    """
    Обмен токенов через Uniswap v3 exactInputSingle.
    """
    try:
        acct = Account.from_key(user_private_key)
        from_token_contract = web3.eth.contract(address=Web3.to_checksum_address(from_token), abi=ERC20_ABI)
        to_token_contract = web3.eth.contract(address=Web3.to_checksum_address(to_token), abi=ERC20_ABI)

        decimals = from_token_contract.functions.decimals().call()
        amount_in = int(amount * (10 ** decimals))

        # Параметры обмена
        params = {
            "tokenIn": from_token,
            "tokenOut": to_token,
            "fee": 3000,  # Пул с 0.3% комиссией. Измените при необходимости.
            "recipient": acct.address,
            "deadline": int(datetime.utcnow().timestamp()) + 60 * 20,  # 20 минут
            "amountIn": amount_in,
            "amountOutMinimum": 0,  # Можно установить минимально допустимый объем
            "sqrtPriceLimitX96": 0  # Без ограничения цены
        }

        # Одобрение токенов, если необходимо
        allowance = from_token_contract.functions.allowance(acct.address, UNISWAP_ROUTER_ADDRESS).call()
        if allowance < amount_in:
            logger.info(f"Недостаточно allowance для {from_token}. Выполняется одобрение.")
            approved = approve_token(user_private_key, from_token_contract, UNISWAP_ROUTER_ADDRESS, amount_in)
            if not approved:
                logger.error("Не удалось одобрить токены для Uniswap.")
                return False

        # Построение транзакции обмена
        swap_tx = swap_router_contract.functions.exactInputSingle(params).build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce": web3.eth.get_transaction_count(acct.address, 'pending'),
            "gas": 200000,  # Увеличьте при необходимости
            "gasPrice": web3.to_wei('50', 'gwei'),
            "value": 0  # Для токенов, отличных от ETH
        })

        # Подписание и отправка транзакции
        signed_swap_tx = acct.sign_transaction(swap_tx)
        tx_hash = web3.eth.send_raw_transaction(signed_swap_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        if receipt.status == 1:
            logger.info(f"swap_tokens_via_uniswap_v3: Обмен успешно выполнен, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"swap_tokens_via_uniswap_v3 fail: {tx_hash.hex()}")
            return False

    except Exception as e:
        logger.error("swap_tokens_via_uniswap_v3 except", exc_info=True)
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
    except Exception as e:
        db.session.rollback()
        logger.error(f"accumulate_staking_rewards except: {e}", exc_info=True)
