# staking_logic.py

import os
import logging
import traceback
from datetime import datetime, timedelta
import requests

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
    TOKEN_CONTRACT_ADDRESS == "0xYOUR_TOKEN_CONTRACT_ADDRESS" or
    WETH_CONTRACT_ADDRESS == "0xYOUR_WETH_CONTRACT_ADDRESS" or
    PROJECT_WALLET_ADDRESS == "0xYOUR_PROJECT_WALLET_ADDRESS"
):
    logger.error("Одна или несколько необходимых переменных окружения (TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS) не установлены или содержат плейсхолдеры.")
    raise ValueError("Некорректные значения переменных окружения: TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS.")

# Стандартный ERC20 ABI с необходимыми функциями
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
    # Добавьте другие необходимые функции, если необходимо
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

# Подключение контрактов с использованием полного ERC20 ABI
token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS), abi=ERC20_ABI)
weth_contract = web3.eth.contract(address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS), abi=ERC20_ABI)
ujo_contract = web3.eth.contract(address=Web3.to_checksum_address(UJO_CONTRACT_ADDRESS), abi=ERC20_ABI)

def generate_unique_wallet():
    """
    Генерирует уникальный Ethereum кошелек (адрес и приватный ключ).
    """
    account = Account.create()
    wallet_address = account.address
    private_key = account.key.hex()
    logger.info(f"Сгенерирован кошелек: {wallet_address}")
    return wallet_address, private_key

def send_token_reward(to_address: str, amount: float, from_address: str = PROJECT_WALLET_ADDRESS) -> bool:
    """
    Отправляет токены UJO на указанный адрес.
    amount: количество UJO (не в wei)
    from_address: адрес отправителя (по умолчанию PROJECT_WALLET_ADDRESS)
    """
    try:
        # Получение приватного ключа проекта из переменных окружения
        project_private_key = os.environ.get("PRIVATE_KEY", "")
        if not project_private_key:
            logger.error("PRIVATE_KEY не задан в переменных окружения.")
            return False

        # Создание аккаунта проекта
        project_account = Account.from_key(project_private_key)

        # Конвертация количества UJO в wei
        amount_wei = int(amount * (10 ** 18))  # Предполагается 18 десятичных знаков

        # Подготовка транзакции
        tx = ujo_contract.functions.transfer(Web3.to_checksum_address(to_address), amount_wei).build_transaction({
            'chainId': web3.eth.chain_id,
            'gas': 100000,  # Установите подходящий лимит газа
            'gasPrice': web3.eth.gas_price,
            'nonce': web3.eth.get_transaction_count(project_account.address)
        })

        # Подписание транзакции
        signed_tx = project_account.sign_transaction(tx)

        # Отправка транзакции
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Отправлена транзакция {tx_hash.hex()} для отправки {amount} UJO на {to_address}.")

        # Ожидание подтверждения
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

def get_token_balance(wallet_address: str, contract=None) -> float:
    """
    Получает баланс токена для указанного адреса.
    Если contract не указан, берется UJO контракт.
    """
    try:
        if contract is None:
            contract = ujo_contract
        balance = contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        decimals = 18  # Предполагается 18 десятичных знаков; измените, если другое
        return balance / (10 ** decimals)
    except Exception as e:
        logger.error(f"Ошибка при получении баланса токена для {wallet_address}: {e}")
        logger.error(traceback.format_exc())
        return 0.0

def exchange_weth_to_ujo(wallet_address: str, amount_weth: float) -> bool:
    """
    Обменивает WETH на UJO для указанного адреса.
    """
    try:
        # Получение приватного ключа пользователя
        user = User.query.filter_by(unique_wallet_address=wallet_address).first()
        if not user or not user.unique_private_key:
            logger.error(f"Пользователь с кошельком {wallet_address} не найден или не имеет приватного ключа.")
            return False

        user_account = Account.from_key(user.unique_private_key)

        # Конвертация количества WETH в wei
        amount_weth_wei = int(amount_weth * (10 ** 18))  # Предполагается 18 десятичных знаков

        # Проверка баланса WETH пользователя
        weth_balance = weth_contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        if weth_balance < amount_weth_wei:
            logger.error(f"Недостаточно WETH на кошельке {wallet_address}.")
            return False

        # Подготовка транзакции: перевод WETH на проектный кошелек
        tx = weth_contract.functions.transfer(Web3.to_checksum_address(PROJECT_WALLET_ADDRESS), amount_weth_wei).build_transaction({
            'chainId': web3.eth.chain_id,
            'gas': 100000,  # Установите подходящий лимит газа
            'gasPrice': web3.eth.gas_price,
            'nonce': web3.eth.get_transaction_count(user_account.address)
        })

        # Подписание транзакции
        signed_tx = user_account.sign_transaction(tx)

        # Отправка транзакции
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Отправлена транзакция {tx_hash.hex()} для обмена {amount_weth} WETH от {wallet_address}.")

        # Ожидание подтверждения
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            logger.info(f"Транзакция {tx_hash.hex()} успешно подтверждена.")
            # После получения WETH, проектный кошелек должен обменять их на UJO и отправить пользователю
            # Это требует интеграции с DEX или другого механизма обмена
            # Для псевдостейкинга предположим фиксированный обменный курс
            exchange_rate = 10  # Пример: 1 WETH = 10 UJO
            ujo_amount = amount_weth * exchange_rate
            success = send_token_reward(wallet_address, ujo_amount)
            if success:
                logger.info(f"Обмен WETH на UJO для {wallet_address} успешно выполнен.")
                return True
            else:
                logger.error(f"Отправка UJO пользователю {wallet_address} не удалась.")
                return False
        else:
            logger.error(f"Транзакция {tx_hash.hex()} не удалась.")
            return False

    except Exception as e:
        logger.error(f"Ошибка при обмене WETH на UJO для {wallet_address}: {e}")
        logger.error(traceback.format_exc())
        return False

def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """
    Фронтенд (после успешной транзакции) отправляет txHash сюда.
    Мы проверяем:
      1) транзакция успешна (receipt.status == 1);
      2) Логи содержат Transfer(from=user.unique_wallet_address, to=PROJECT_WALLET_ADDRESS, >=25$);
      3) Создаём запись UserStaking(...).
    """
    if not user or not user.unique_wallet_address or not tx_hash:
        logger.warning("confirm_staking_tx: не хватает данных (user/txHash).")
        return False

    try:
        receipt = web3.eth.get_transaction_receipt(tx_hash)
        if not receipt or receipt.status != 1:
            logger.warning(f"Tx {tx_hash} не успешен (receipt.status != 1).")
            return False

        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        price_usd = get_token_price_in_usd()
        if price_usd <= 0:
            logger.warning("Цена токена <= 0, прерываем confirm_staking_tx.")
            return False

        found_transfer = None

        # Перебираем логи в receipt, ищем событие Transfer(...)
        for log in receipt.logs:
            # Сравниваем адрес контракта
            if log.address.lower() == token_contract.address.lower():
                # Проверяем, что topics[0] == Transfer(...)
                if len(log.topics) >= 3:
                    if log.topics[0].hex().lower() == transfer_topic.lower():
                        from_addr = "0x" + log.topics[1].hex()[26:]
                        to_addr = "0x" + log.topics[2].hex()[26:]
                        from_addr = Web3.to_checksum_address(from_addr)
                        to_addr = Web3.to_checksum_address(to_addr)

                        if (from_addr.lower() == user.unique_wallet_address.lower() and
                            to_addr.lower()   == PROJECT_WALLET_ADDRESS.lower()):
                            # Получаем amount из data
                            amount_int = int(log.data, 16)
                            amount_token = amount_int / (10 ** 18)  # Предполагается 18 десятичных знаков
                            amount_usd = amount_token * price_usd

                            # Нужно >= 25$ (включая 20$ стейк и 5$ сбор).
                            if amount_usd >= 25.0:
                                found_transfer = {
                                    "token_amount": amount_token,
                                    "usd_amount": amount_usd
                                }
                                break

        if not found_transfer:
            logger.warning(f"Tx {tx_hash}: не нашли нужный Transfer >= 25$ (UJO).")
            return False

        # Проверим, не обрабатывали ли мы этот tx
        existing = UserStaking.query.filter_by(tx_hash=tx_hash).first()
        if existing:
            logger.warning(f"Tx {tx_hash} уже есть в UserStaking.")
            return False

        # Создаём запись в таблице стейков
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

        # Делаем user.assistant_premium = True (иначе user не увидит премиум-функции)
        user.assistant_premium = True

        db.session.commit()
        logger.info(
            f"User {user.id} застейкал ~{found_transfer['usd_amount']:.2f}$ (tx={tx_hash}). Premium on."
        )
        return True

    except Exception as e:
        logger.error(f"Ошибка confirm_staking_tx(tx={tx_hash}): {e}")
        logger.error(traceback.format_exc())
        db.session.rollback()
        return False

def accumulate_staking_rewards():
    """
    Раз в неделю (или раз в день) увеличиваем pending_rewards в UserStaking (эмуляция).
    """
    try:
        stakings = UserStaking.query.all()
        for s in stakings:
            if s.staked_amount > 0:
                # Пример: +0.5 UJO за период
                s.pending_rewards += 0.5
        db.session.commit()
        logger.info("accumulate_staking_rewards: награды добавлены всем стейкерам.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"accumulate_staking_rewards: {e}")
        logger.error(traceback.format_exc())

def get_token_price_in_usd() -> float:
    """
    Получает текущую цену токена UJO в USD через DexScreener API.
    """
    try:
        pair_address = os.environ.get("DEXScreener_PAIR_ADDRESS", "")
        if not pair_address:
            logger.error("DEXScreener_PAIR_ADDRESS не задан.")
            return 0.0

        # Корректный URL для DexScreener API
        chain_name = "bsc"  # Измените на нужную цепочку
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"
        
        logger.info(f"Отправка запроса к DexScreener API: {api_url}")
        resp = requests.get(api_url, timeout=10)
        
        logger.info(f"API Response Status: {resp.status_code}")
        logger.info(f"API Response Body: {resp.text}")
        
        if resp.status_code != 200:
            logger.error(f"DexScreener API вернул статус {resp.status_code}")
            return 0.0
        
        data = resp.json()
        pair = data.get("pair", {})
        if not pair:
            logger.warning("DexScreener pair отсутствует или не вернулся.")
            return 0.0
        
        price_usd_str = pair.get("priceUsd", "0.0")
        price_usd = float(price_usd_str)
        logger.info(f"Текущая цена токена UJO: {price_usd} USD")
        return price_usd
    except ValueError as e:
        logger.error(f"Ошибка при декодировании JSON: {e}")
        logger.error(f"Тело ответа: {resp.text}")
        return 0.0
    except Exception as e:
        logger.error(f"Ошибка get_token_price_in_usd: {e}")
        logger.error(traceback.format_exc())
        return 0.0
