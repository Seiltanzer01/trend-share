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
INFURA_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID")  # Замените на URL вашего провайдера
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Адреса контрактов
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS", "0xYOUR_TOKEN_CONTRACT_ADDRESS")
WETH_CONTRACT_ADDRESS = os.environ.get("WETH_CONTRACT_ADDRESS", "0xYOUR_WETH_CONTRACT_ADDRESS")  # Добавьте эту переменную в Render
UJO_CONTRACT_ADDRESS = TOKEN_CONTRACT_ADDRESS  # Если UJO — это тот же токен
PROJECT_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "0xYOUR_PROJECT_WALLET_ADDRESS")

# Проверка наличия необходимых переменных окружения
if (
    TOKEN_CONTRACT_ADDRESS == "0xYOUR_TOKEN_CONTRACT_ADDRESS"
    or WETH_CONTRACT_ADDRESS == "0xYOUR_WETH_CONTRACT_ADDRESS"
    or PROJECT_WALLET_ADDRESS == "0xYOUR_PROJECT_WALLET_ADDRESS"
):
    logger.error("Одна или несколько необходимых переменных окружения (TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS) не установлены или содержат плейсхолдеры.")
    raise ValueError("Некорректные значения переменных окружения: TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS.")

# Стандартный ERC20 ABI
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
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

# Подключение контрактов
token_contract = web3.eth.contract(
    address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)
weth_contract = web3.eth.contract(
    address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)
ujo_contract = web3.eth.contract(
    address=Web3.to_checksum_address(UJO_CONTRACT_ADDRESS),
    abi=ERC20_ABI
)

def generate_unique_wallet_address():
    """
    Генерирует уникальный адрес кошелька в формате checksum.
    """
    while True:
        address = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(40))
        try:
            checksum_address = Web3.to_checksum_address(address)
        except ValueError:
            continue
        # Проверяем, нет ли уже такого в БД
        if not User.query.filter_by(unique_wallet_address=checksum_address).first():
            return checksum_address

def generate_unique_private_key():
    """
    Генерирует уникальный приватный ключ.
    """
    private_key = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(64))
    return private_key

def send_token_reward(to_address: str, amount: float, from_address: str = PROJECT_WALLET_ADDRESS, private_key: str = None) -> bool:
    """
    Отправляет токены UJO на указанный адрес.
    amount: количество UJO (не в wei)
    from_address: адрес отправителя (по умолчанию PROJECT_WALLET_ADDRESS)
    private_key: приватный ключ отправителя. Если None, используется PROJECT_PRIVATE_KEY
    """
    try:
        if private_key:
            sender_account = Account.from_key(private_key)
        else:
            project_private_key = os.environ.get("PRIVATE_KEY", "")
            if not project_private_key:
                logger.error("PRIVATE_KEY не задан в переменных окружения.")
                return False
            sender_account = Account.from_key(project_private_key)

        decimals = token_contract.functions.decimals().call()
        amount_wei = int(amount * (10 ** decimals))

        tx = token_contract.functions.transfer(
            Web3.to_checksum_address(to_address), amount_wei
        ).build_transaction({
            'chainId': web3.eth.chain_id,
            'gas': 100000,
            'gasPrice': web3.eth.gas_price,
            'nonce': web3.eth.get_transaction_count(sender_account.address)
        })

        signed_tx = sender_account.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Отправлена транзакция {tx_hash.hex()} для отправки {amount} UJO на {to_address}.")

        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            logger.info(f"Транзакция {tx_hash.hex()} успешно подтверждена.")
            return True
        else:
            logger.error(f"Транзакция {tx_hash.hex()} не удалась.")
            return False

    except Exception as e:
        logger.error(f"Ошибка при отправке токенов: {e}")
        logger.error(traceback.format_exc())
        return False

def send_eth(to_address: str, amount_eth: float, private_key: str) -> bool:
    """
    Отправляет ETH на указанный адрес.
    """
    try:
        account = Account.from_key(private_key)
        nonce = web3.eth.get_transaction_count(account.address)
        tx = {
            'nonce': nonce,
            'to': Web3.to_checksum_address(to_address),
            'value': Web3.to_wei(amount_eth, 'ether'),
            'gas': 21000,
            'gasPrice': web3.eth.gas_price,
            'chainId': web3.eth.chain_id
        }
        signed_tx = account.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Отправлена транзакция {tx_hash.hex()} для отправки {amount_eth} ETH на {to_address}.")
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            logger.info(f"Транзакция {tx_hash.hex()} успешно подтверждена.")
            return True
        else:
            logger.error(f"Транзакция {tx_hash.hex()} не удалась.")
            return False
    except Exception as e:
        logger.error(f"Ошибка при отправке ETH: {e}")
        logger.error(traceback.format_exc())
        return False

def get_token_balance(wallet_address: str, contract=None) -> float:
    """
    Получает баланс указанного токена. По умолчанию UJO.
    """
    try:
        if contract is None:
            contract = ujo_contract
        balance = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        decimals = contract.functions.decimals().call()
        return balance / (10 ** decimals)
    except Exception as e:
        logger.error(f"Ошибка при получении баланса токена для {wallet_address}: {e}")
        logger.error(traceback.format_exc())
        return 0.0

def get_balances(user: User) -> dict:
    """
    Возвращает балансы ETH, WETH, UJO для данного пользователя.
    """
    try:
        unique_wallet_address = Web3.to_checksum_address(user.unique_wallet_address)

        eth_balance = web3.eth.get_balance(unique_wallet_address)
        eth_balance = Web3.from_wei(eth_balance, 'ether')

        weth_balance = get_token_balance(unique_wallet_address, weth_contract)
        ujo_balance = get_token_balance(unique_wallet_address, ujo_contract)

        return {
            "balances": {
                "eth": float(eth_balance),
                "weth": float(weth_balance),
                "ujo": float(ujo_balance)
            }
        }
    except Exception as e:
        logger.error(f"Ошибка при get_balances для пользователя {user.id}: {e}")
        logger.error(traceback.format_exc())
        return {"error": "Internal server error."}

def exchange_weth_to_ujo(wallet_address: str, amount_weth: float) -> bool:
    """
    Простая демонстрация "WETH -> UJO" через отправку WETH на PROJECT_WALLET,
    и псевдо-отправку UJO обратно пользователю (без реальной DEX-логики).
    Для реального обмена с 0x используйте функции ниже.
    """
    try:
        user = User.query.filter_by(unique_wallet_address=wallet_address).first()
        if not user or not user.unique_private_key:
            logger.error(f"Нет приватного ключа для кошелька {wallet_address}.")
            return False

        user_account = Account.from_key(user.unique_private_key)

        # decimals
        weth_dec = weth_contract.functions.decimals().call()
        amount_weth_wei = int(amount_weth * 10**weth_dec)

        # Проверка баланса
        current_weth_balance = weth_contract.functions.balanceOf(wallet_address).call()
        if current_weth_balance < amount_weth_wei:
            logger.error("Недостаточно WETH.")
            return False

        # 1) Отправляем WETH -> project wallet
        tx = weth_contract.functions.transfer(
            Web3.to_checksum_address(PROJECT_WALLET_ADDRESS), amount_weth_wei
        ).build_transaction({
            'chainId': web3.eth.chain_id,
            'gas': 100000,
            'gasPrice': web3.eth.gas_price,
            'nonce': web3.eth.get_transaction_count(user_account.address)
        })
        signed = user_account.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            logger.error("Перевод WETH не удался.")
            return False

        logger.info(f"Успешная транзакция WETH->ProjectWallet: {tx_hash.hex()}")
        # 2) Отправляем UJO обратно на кошелек
        # Допустим, курс 1 WETH = 10 UJO (псевдо)
        ujo_amount = amount_weth * 10
        success = send_token_reward(
            wallet_address, ujo_amount,
            from_address=PROJECT_WALLET_ADDRESS
        )
        return success

    except Exception as e:
        logger.error(f"Ошибка exchange_weth_to_ujo: {e}")
        logger.error(traceback.format_exc())
        return False

def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """
    Проверяем, что пользователь действительно отправил >=25$ (20$ стейк + 5$ сбор).
    """
    if not user or not user.unique_wallet_address or not tx_hash:
        logger.warning("confirm_staking_tx: не хватает данных.")
        return False

    try:
        receipt = web3.eth.get_transaction_receipt(tx_hash)
        if not receipt or receipt.status != 1:
            logger.warning("Транзакция не успешна.")
            return False

        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        price_usd = get_token_price_in_usd()
        if price_usd <= 0:
            logger.warning("Цена токена <= 0.")
            return False

        found_transfer = None
        for log in receipt.logs:
            if log.address.lower() == token_contract.address.lower():
                if len(log.topics) >= 3:
                    if log.topics[0].hex().lower() == transfer_topic.lower():
                        from_addr = "0x" + log.topics[1].hex()[26:]
                        to_addr = "0x" + log.topics[2].hex()[26:]
                        from_addr = Web3.to_checksum_address(from_addr)
                        to_addr = Web3.to_checksum_address(to_addr)

                        if (from_addr.lower() == user.unique_wallet_address.lower()
                            and to_addr.lower() == PROJECT_WALLET_ADDRESS.lower()):
                            amount_int = int(log.data, 16)
                            amount_token = amount_int / (10 ** 18)
                            amount_usd = amount_token * price_usd

                            if amount_usd >= 25.0:
                                found_transfer = {
                                    "token_amount": amount_token,
                                    "usd_amount": amount_usd
                                }
                                break
        if not found_transfer:
            logger.warning("Tx не нашёл Transfer >=25$.")
            return False

        # Проверим, нет ли дубля
        existing = UserStaking.query.filter_by(tx_hash=tx_hash).first()
        if existing:
            logger.warning(f"Tx {tx_hash} уже есть.")
            return False

        # Создаём запись
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
        logger.info(f"Стейк {found_transfer['usd_amount']:.2f}$ подтверждён.")
        return True

    except Exception as e:
        logger.error(f"Ошибка confirm_staking_tx: {e}")
        logger.error(traceback.format_exc())
        db.session.rollback()
        return False

def accumulate_staking_rewards():
    """
    Пример: каждые X времени добавляем всем +0.5 UJO.
    """
    try:
        stakings = UserStaking.query.all()
        for s in stakings:
            if s.staked_amount > 0:
                s.pending_rewards += 0.5
        db.session.commit()
        logger.info("accumulate_staking_rewards: награды добавлены.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"accumulate_staking_rewards: {e}")
        logger.error(traceback.format_exc())

def get_token_price_in_usd() -> float:
    """
    Получает примерную цену UJO через DexScreener. Можно подставить реальный pair_address.
    """
    try:
        pair_address = os.environ.get("DEXScreener_PAIR_ADDRESS", "")
        if not pair_address:
            logger.error("DEXScreener_PAIR_ADDRESS не задан.")
            return 0.0

        chain_name = "bsc"  # или base, arbitrum... зависит от вашего токена
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"

        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"DexScreener вернул {resp.status_code}")
            return 0.0

        data = resp.json()
        pair = data.get("pair", {})
        if not pair:
            return 0.0

        price_usd_str = pair.get("priceUsd", "0.0")
        price_usd = float(price_usd_str)
        return price_usd
    except Exception as e:
        logger.error(f"Ошибка get_token_price_in_usd: {e}")
        logger.error(traceback.format_exc())
        return 0.0

########################################################################
# НИЖЕ - ПРИМЕР ПОЛНОЙ ИНТЕГРАЦИИ С 0x (approve + swap)                #
########################################################################

def get_0x_quote(sell_token: str, buy_token: str, sell_amount_wei: int, taker_address: str) -> dict:
    # БЕРЁМ 0x API key ИЗ ОКРУЖЕНИЯ
    zerox_api_key = os.environ.get("ZEROX_API_KEY", "").strip()
    if not zerox_api_key:
        logger.error("ZEROX_API_KEY не задан в переменных окружения!")
        return {}

    url = "https://api.0x.org/swap/v1/quote"
    params = {
        "chainId": "8453",  # Base
        "sellToken": sell_token,
        "buyToken": buy_token,
        "sellAmount": str(sell_amount_wei),
        "takerAddress": taker_address,
        # при желании: "slippagePercentage": "0.02"
    }
    headers = {
        "0x-api-key": zerox_api_key
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.error(f"Ошибка get_0x_quote: {resp.text}")
            return {}
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка get_0x_quote: {e}")
        return {}

def approve_0x(token_address: str, spender: str, amount_wei: int, private_key: str) -> bool:
    """
    Делаем approve(spender, amount_wei) для указанного токена.
    """
    try:
        account = Account.from_key(private_key)
        erc20 = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)

        nonce = web3.eth.get_transaction_count(account.address)
        tx = erc20.functions.approve(
            Web3.to_checksum_address(spender),
            amount_wei
        ).build_transaction({
            'chainId': web3.eth.chain_id,
            'gas': 100000,
            'gasPrice': web3.eth.gas_price,
            'nonce': nonce
        })
        signed = account.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        logger.info(f"Отправлен approve tx: {tx_hash.hex()}")
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return (receipt.status == 1)
    except Exception as e:
        logger.error(f"Ошибка approve_0x: {e}")
        return False

def execute_0x_swap(quote_data: dict, private_key: str) -> bool:
    """
    Подписываем транзакцию `to=quote_data["to"]`, data=..., value=...
    и отправляем. Ждём receipt.
    """
    try:
        account = Account.from_key(private_key)
        tx = {
            "to": Web3.to_checksum_address(quote_data["to"]),
            "data": quote_data["data"],
            "gasPrice": int(quote_data["gasPrice"]),
            "gas": int(quote_data.get("gas", 300000)),
            "nonce": web3.eth.get_transaction_count(account.address),
            "chainId": web3.eth.chain_id
        }
        # Может быть value>0, если продаём ETH
        val = quote_data.get("value", "0")
        tx["value"] = int(val)

        signed_tx = web3.eth.account.sign_transaction(tx, private_key)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Отправлена swap-транзакция: {tx_hash.hex()}")
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info("Обмен через 0x Swap API прошёл успешно!")
            return True
        else:
            logger.error("Обмен через 0x Swap API не удался, статус !=1")
            return False
    except Exception as e:
        logger.error(f"Ошибка execute_0x_swap: {e}")
        return False
