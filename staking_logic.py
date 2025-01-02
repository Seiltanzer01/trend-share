# staking_logic.py

import os
import logging
import traceback
from datetime import datetime, timedelta
import requests
import secrets
import string

from web3 import Web3, HTTPProvider
from eth_account import Account

from models import db, User, UserStaking

logger = logging.getLogger(__name__)

# Настройки
INFURA_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID")
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Адреса контрактов
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS", "0xYOUR_TOKEN_CONTRACT_ADDRESS")
WETH_CONTRACT_ADDRESS = os.environ.get("WETH_CONTRACT_ADDRESS", "0xYOUR_WETH_CONTRACT_ADDRESS")
UJO_CONTRACT_ADDRESS = TOKEN_CONTRACT_ADDRESS  # Если UJO — это тот же токен
PROJECT_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "0xYOUR_PROJECT_WALLET_ADDRESS")

# Проверка наличия необходимых переменных окружения
if (
    TOKEN_CONTRACT_ADDRESS == "0xYOUR_TOKEN_CONTRACT_ADDRESS" or
    WETH_CONTRACT_ADDRESS == "0xYOUR_WETH_CONTRACT_ADDRESS" or
    PROJECT_WALLET_ADDRESS == "0xYOUR_PROJECT_WALLET_ADDRESS"
):
    logger.error("Одна или несколько необходимых ENV переменных (TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS) не установлены.")
    raise ValueError("Некорректные значения ENV: TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS.")

# Стандартный ERC20 ABI (добавлен метод decimals)
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
]

# Проверка валидности адресов
if not Web3.is_address(TOKEN_CONTRACT_ADDRESS):
    logger.error(f"Некорректный TOKEN_CONTRACT_ADDRESS: {TOKEN_CONTRACT_ADDRESS}")
    raise ValueError(f"Некорректный TOKEN_CONTRACT_ADDRESS: {TOKEN_CONTRACT_ADDRESS}")

if not Web3.is_address(WETH_CONTRACT_ADDRESS):
    logger.error(f"Некорректный WETH_CONTRACT_ADDRESS: {WETH_CONTRACT_ADDRESS}")
    raise ValueError(f"Некорректный WETH_CONTRACT_ADDRESS: {WETH_CONTRACT_ADDRESS}")

if not Web3.is_address(UJO_CONTRACT_ADDRESS):
    logger.error(f"Некорректный UJO_CONTRACT_ADDRESS: {UJO_CONTRACT_ADDRESS}")
    raise ValueError(f"Некорректный UJO_CONTRACT_ADDRESS: {UJO_CONTRACT_ADDRESS}")

if not Web3.is_address(PROJECT_WALLET_ADDRESS):
    logger.error(f"Некорректный PROJECT_WALLET_ADDRESS: {PROJECT_WALLET_ADDRESS}")
    raise ValueError(f"Некорректный PROJECT_WALLET_ADDRESS: {PROJECT_WALLET_ADDRESS}")

# Подключаем контракты
token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS), abi=ERC20_ABI)
weth_contract = web3.eth.contract(address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS), abi=ERC20_ABI)
ujo_contract  = web3.eth.contract(address=Web3.to_checksum_address(UJO_CONTRACT_ADDRESS),  abi=ERC20_ABI)

# Подготовка для 0x Swap v2
ZEROX_API_KEY = os.environ.get("ZEROX_API_KEY", "")
DEFAULT_0X_HEADERS = {
    "0x-api-key": ZEROX_API_KEY,
    "0x-version": "v2",  # ключ для v2
}

def generate_unique_wallet_address():
    while True:
        address = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(40))
        try:
            checksum_address = Web3.to_checksum_address(address)
        except ValueError:
            continue
        if not User.query.filter_by(unique_wallet_address=checksum_address).first():
            return checksum_address

def generate_unique_private_key():
    private_key = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(64))
    return private_key


def get_token_balance(wallet_address: str, contract=None) -> float:
    """Получить баланс токена (по умолчанию UJO)."""
    try:
        if contract is None:
            contract = ujo_contract
        raw_balance = contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        decimals = contract.functions.decimals().call()
        return raw_balance / (10 ** decimals)
    except Exception as e:
        logger.error(f"Ошибка get_token_balance({wallet_address}): {e}")
        logger.error(traceback.format_exc())
        return 0.0

def send_token_reward(to_address: str, amount: float, from_address: str = PROJECT_WALLET_ADDRESS, private_key: str = None) -> bool:
    """Отправка UJO-токенов с приватным ключом (или PROJECT_PRIVATE_KEY)."""
    try:
        if private_key:
            sender_account = Account.from_key(private_key)
        else:
            project_private_key = os.environ.get("PRIVATE_KEY", "")
            if not project_private_key:
                logger.error("PRIVATE_KEY не задан.")
                return False
            sender_account = Account.from_key(project_private_key)

        decimals = token_contract.functions.decimals().call()
        amount_wei = int(amount * (10 ** decimals))

        tx = token_contract.functions.transfer(Web3.to_checksum_address(to_address), amount_wei).build_transaction({
            'chainId': web3.eth.chain_id,
            'gas': 100000,
            'gasPrice': web3.eth.gas_price,
            'nonce': web3.eth.get_transaction_count(sender_account.address, 'pending')
        })
        signed_tx = sender_account.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"send_token_reward: {amount} UJO -> {to_address}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"send_token_reward fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error(f"Ошибка send_token_reward: {e}")
        logger.error(traceback.format_exc())
        return False

def send_eth(to_address: str, amount_eth: float, private_key: str) -> bool:
    """Отправка ETH."""
    try:
        account = Account.from_key(private_key)
        nonce = web3.eth.get_transaction_count(account.address, 'pending')
        tx = {
            'nonce': nonce,
            'to': Web3.to_checksum_address(to_address),
            'value': web3.to_wei(amount_eth, 'ether'),
            'gas': 21000,
            'gasPrice': web3.eth.gas_price,
            'chainId': web3.eth.chain_id,
        }
        signed_tx = account.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"send_eth: {amount_eth} ETH -> {to_address}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"send_eth fail: {tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error(f"Ошибка send_eth: {e}")
        logger.error(traceback.format_exc())
        return False


def get_balances(user: User) -> dict:
    """Возвращает балансы ETH, WETH, UJO для данного user."""
    try:
        unique_wallet_address = Web3.to_checksum_address(user.unique_wallet_address)

        eth_balance_wei  = web3.eth.get_balance(unique_wallet_address)
        eth_balance      = Web3.from_wei(eth_balance_wei, 'ether')

        weth_dec = weth_contract.functions.decimals().call()
        raw_weth = weth_contract.functions.balanceOf(unique_wallet_address).call()
        weth_bal = raw_weth / (10**weth_dec)

        ujo_bal  = get_token_balance(unique_wallet_address, ujo_contract)

        return {
            "balances": {
                "eth": float(eth_balance),
                "weth": float(weth_bal),
                "ujo": float(ujo_bal)
            }
        }
    except Exception as e:
        logger.error(f"Ошибка get_balances(user_id={user.id}): {e}")
        logger.error(traceback.format_exc())
        return {"error": "Internal server error."}


def get_token_price_in_usd() -> float:
    """
    Получает текущую цену UJO в USD (через DexScreener), 
    если нет ликвидности — вернётся 0.0
    """
    try:
        pair_address = os.environ.get("DEXScreener_PAIR_ADDRESS", "")
        if not pair_address:
            logger.error("DEXScreener_PAIR_ADDRESS не задан.")
            return 0.0

        # Для Base может не работать "bsc"? Укажите корректную цепочку, например "base"
        # Уточните, поддерживает ли DexScreener "base" / "ethereum" / "bsc"...
        chain_name = "base"  # пример
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"

        logger.info(f"Запрос к DexScreener API: {api_url}")
        resp = requests.get(api_url, timeout=10)
        logger.info(f"DexScreener resp: {resp.status_code}, {resp.text}")
        if resp.status_code != 200:
            logger.error(f"DexScreener API code={resp.status_code}")
            return 0.0

        data = resp.json()
        pair = data.get("pair", {})
        if not pair:
            return 0.0

        price_usd_str = pair.get("priceUsd", "0.0")
        price_usd = float(price_usd_str)
        return price_usd
    except:
        logger.error("get_token_price_in_usd exception", exc_info=True)
        return 0.0


# ---------------------------
# **Ниже: 0x swap v2 (permit2)**
# ---------------------------

def get_0x_quote_v2_permit2(
    sell_token: str,
    buy_token: str,
    sell_amount_wei: int,
    taker_address: str,
    chain_id: int = 8453
) -> dict:
    """
    Получение котировки v2 permit2
    https://api.0x.org/swap/permit2/quote

    sell_token: '0xeeee...' (ETH) либо адрес ERC20
    buy_token:  '0xeeee...' (ETH) либо адрес ERC20
    sell_amount_wei: int (кол-во в wei)
    taker_address: это user.unique_wallet_address
    chain_id: например, 8453 (Base) или 1 (mainnet)
    """
    if not ZEROX_API_KEY:
        logger.error("ZEROX_API_KEY не задан. Нельзя вызвать 0x.")
        return {}

    url = "https://api.0x.org/swap/permit2/quote"
    params = {
        "chainId": chain_id,
        "sellToken": sell_token,
        "buyToken": buy_token,
        "sellAmount": str(sell_amount_wei),
        "taker": taker_address,
    }
    try:
        resp = requests.get(url, params=params, headers=DEFAULT_0X_HEADERS, timeout=20)
        if resp.status_code != 200:
            raise ValueError(f"Ошибка get_0x_quote_v2_permit2: {resp.text}")
        quote_data = resp.json()
        return quote_data
    except Exception as e:
        logger.error(f"Ошибка get_0x_quote_v2_permit2: {e}")
        logger.error(traceback.format_exc())
        return {}

def execute_0x_swap_v2_permit2(quote_json: dict, private_key: str) -> bool:
    """
    Подписываем и отправляем транзакцию из quote_json["transaction"] 
    (упрощённо, без permit2 eip712-логики).
    """
    if not quote_json:
        logger.error("execute_0x_swap_v2_permit2: quote_json пуст.")
        return False

    tx_obj = quote_json.get("transaction", {})
    to_addr  = tx_obj.get("to")
    data_hex = tx_obj.get("data")
    val_str  = tx_obj.get("value", "0")
    gas_str  = tx_obj.get("gas", "500000")
    gasPrice_str = tx_obj.get("gasPrice", f"{web3.eth.gas_price}")

    if not to_addr or not data_hex:
        logger.error("execute_0x_swap_v2_permit2: нет to/data.")
        return False

    try:
        tx_value = int(val_str)
        tx_gas   = int(gas_str)
        tx_gasPrice = int(gasPrice_str)
    except:
        logger.error("execute_0x_swap_v2_permit2: ошибка parse value/gas/gasPrice.")
        return False

    acct = Account.from_key(private_key)
    nonce = web3.eth.get_transaction_count(acct.address, 'pending')

    tx = {
        "chainId": web3.eth.chain_id,
        "to": Web3.to_checksum_address(to_addr),
        "data": data_hex,
        "value": tx_value,
        "gas": tx_gas,
        "gasPrice": tx_gasPrice,
        "nonce": nonce,
    }
    try:
        signed = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"execute_0x_swap_v2_permit2 success, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"execute_0x_swap_v2_permit2 fail, tx={tx_hash.hex()}")
            return False
    except Exception as e:
        logger.error("execute_0x_swap_v2_permit2: exception", exc_info=True)
        return False


def exchange_weth_to_ujo(wallet_address: str, amount_weth: float) -> bool:
    """
    Старая функция псевдообмена WETH->UJO. 
    Оставим на случай, если кто-то вызывает specifically.
    """
    try:
        user = User.query.filter_by(unique_wallet_address=wallet_address).first()
        if not user or not user.unique_private_key:
            logger.error("exchange_weth_to_ujo: пользователь не найден/нет private_key.")
            return False

        # Баланс WETH
        weth_dec = weth_contract.functions.decimals().call()
        want_wei = int(amount_weth * (10**weth_dec))
        have_wei = weth_contract.functions.balanceOf(wallet_address).call()
        if have_wei < want_wei:
            logger.error("Недостаточно WETH на кошельке.")
            return False

        # Перевод WETH -> проект
        acct = Account.from_key(user.unique_private_key)
        tx = weth_contract.functions.transfer(PROJECT_WALLET_ADDRESS, want_wei).build_transaction({
            "chainId": web3.eth.chain_id,
            "gas": 100000,
            "gasPrice": web3.eth.gas_price,
            "nonce": web3.eth.get_transaction_count(acct.address, 'pending'),
        })
        signed = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status != 1:
            logger.error("Fail tx transferring WETH to project.")
            return False

        # псевдокурс 1 WETH = 10 UJO
        ujo_amount = amount_weth * 10
        # отправляем UJO обратно user'у
        ok = send_token_reward(wallet_address, ujo_amount)
        return ok
    except:
        logger.error("exchange_weth_to_ujo exception", exc_info=True)
        return False


def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """
    Старый метод: если tx >=25$ => создаём запись UserStaking(...) + user.assistant_premium=True
    """
    if not user or not user.unique_wallet_address or not tx_hash:
        return False

    try:
        receipt = web3.eth.get_transaction_receipt(tx_hash)
        if not receipt or receipt.status != 1:
            return False

        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        price_usd = get_token_price_in_usd()
        if price_usd <= 0:
            return False

        found_transfer = None

        for log in receipt.logs:
            if log.address.lower() == token_contract.address.lower():
                if len(log.topics) >= 3:
                    if log.topics[0].hex().lower() == transfer_topic.lower():
                        from_addr = "0x" + log.topics[1].hex()[26:]
                        to_addr   = "0x" + log.topics[2].hex()[26:]
                        from_addr = Web3.to_checksum_address(from_addr)
                        to_addr   = Web3.to_checksum_address(to_addr)

                        if (from_addr.lower() == user.unique_wallet_address.lower()
                            and to_addr.lower() == PROJECT_WALLET_ADDRESS.lower()):
                            amount_int = int(log.data, 16)
                            # decimals=18
                            token_amt = amount_int / (10**18)
                            usd_amt   = token_amt * price_usd
                            if usd_amt >= 25.0:
                                found_transfer = {
                                    "token_amount": token_amt,
                                    "usd_amount": usd_amt
                                }
                                break
        if not found_transfer:
            return False

        # проверяем дубль
        existing = UserStaking.query.filter_by(tx_hash=tx_hash).first()
        if existing:
            return False

        new_stake = UserStaking(
            user_id=user.id,
            tx_hash=tx_hash,
            staked_usd=found_transfer["usd_amount"],
            staked_amount=found_transfer["token_amount"],
            created_at=datetime.utcnow(),
            unlocked_at=datetime.utcnow() + timedelta(days=30),
            last_claim_at=datetime.utcnow()
        )
        db.session.add(new_stake)
        user.assistant_premium = True
        db.session.commit()
        logger.info(f"User {user.id} застейкал ~{found_transfer['usd_amount']:.2f}$ (tx={tx_hash}). Premium on.")
        return True

    except Exception as e:
        logger.error(f"Ошибка confirm_staking_tx(tx={tx_hash}): {e}")
        logger.error(traceback.format_exc())
        db.session.rollback()
        return False

def accumulate_staking_rewards():
    """
    Пример: раз в неделю можно вызвать. 
    """
    try:
        stakings = UserStaking.query.all()
        for s in stakings:
            if s.staked_amount > 0:
                s.pending_rewards += 0.5
        db.session.commit()
    except:
        db.session.rollback()
        logger.error("accumulate_staking_rewards exception", exc_info=True)
