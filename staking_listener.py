# staking_listener.py

import os
import logging
import requests
import traceback

from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account
from models import db, User, UserStaking

logger = logging.getLogger(__name__)

BASE_RPC_URL = os.environ.get('BASE_RPC_URL', '')
TOKEN_CONTRACT_ADDRESS = os.environ.get('TOKEN_CONTRACT_ADDRESS', '')
TOKEN_DECIMALS = int(os.environ.get('TOKEN_DECIMALS', '18'))

MY_WALLET_ADDRESS = os.environ.get('MY_WALLET_ADDRESS', '0xABC123...')  # общий кошелёк, куда отправляют стейк

ABI_ERC20 = [
    {
        "anonymous": False,
        "inputs": [
          {"indexed": True,"name": "from","type": "address"},
          {"indexed": True,"name": "to","type": "address"},
          {"indexed": False,"name": "value","type": "uint256"}
        ],
        "name": "Transfer",
        "type": "event"
    }
]

LAST_BLOCK_KEY = "staking_listener_last_block"  # можно хранить в Config

def get_price_from_dexscreener() -> float:
    """
    Пример запроса цены с DexScreener (или любая другая цена)
    Допустим, вернём $1.0 (заглушка)
    """
    # Здесь можно сделать реальный запрос, например:
    # url = "https://api.dexscreener.com/latest/dex/tokens/0xYourToken"
    # r = requests.get(url)
    # data = r.json()
    # price = data["pairs"][0]["priceUsd"]
    # return float(price)

    return 1.0

def scan_for_staking_transfers(app):
    """
    Каждую минуту (или другой интервал) смотрим события Transfer(...).
    Ищем transfer, где to == MY_WALLET_ADDRESS.
    Проверяем from в БД => user.wallet_address. 
    Если совпадает - считаем USD, если >=25$, добавляем запись UserStaking.
    """
    if not BASE_RPC_URL or not TOKEN_CONTRACT_ADDRESS:
        logger.error("Не заданы BASE_RPC_URL / TOKEN_CONTRACT_ADDRESS.")
        return

    from models import Config  # локальный импорт, чтобы не было коллизий

    try:
        web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
        if not web3.is_connected():
            logger.error("scan_for_staking_transfers: web3 not connected.")
            return
        web3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # Получим last_block из Config
        last_block_conf = Config.query.filter_by(key=LAST_BLOCK_KEY).first()
        if not last_block_conf:
            # Если не было никогда
            current_block = web3.eth.block_number
            last_block_conf = Config(key=LAST_BLOCK_KEY, value=str(current_block))
            db.session.add(last_block_conf)
            db.session.commit()
            return

        last_block = int(last_block_conf.value)
        current_block = web3.eth.block_number
        if current_block <= last_block:
            logger.info(f"Нет новых блоков для сканирования (current={current_block}, last={last_block}).")
            return

        token_contract = web3.eth.contract(address=web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS), abi=ABI_ERC20)
        event_signature_hash = web3.keccak(text="Transfer(address,address,uint256)").hex()

        logs = web3.eth.get_logs({
            "fromBlock": last_block+1,
            "toBlock": current_block,
            "address": web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
            # можно фильтр topics: first topic = Transfer
            "topics": [event_signature_hash]
        })

        price_usd = get_price_from_dexscreener()  # допустим, цена токена
        logger.info(f"Цена токена (DexScreener) = {price_usd} $.")

        for log_entry in logs:
            # Парсим
            topics = log_entry["topics"]
            data_hex = log_entry["data"]
            # topics[1] = from, topics[2] = to (indexed)
            from_addr = "0x" + topics[1].hex()[26:]
            to_addr   = "0x" + topics[2].hex()[26:]

            # Кол-во токенов:
            amount_wei = int(data_hex, 16)
            amount_tokens = amount_wei / 10**TOKEN_DECIMALS

            # Проверяем, что to == MY_WALLET_ADDRESS
            if to_addr.lower() == MY_WALLET_ADDRESS.lower():
                # Ищем user, у которого wallet_address == from_addr
                user = User.query.filter_by(wallet_address=from_addr.lower()).first()
                if user:
                    # считаем, сколько в USD
                    amount_in_usd = amount_tokens * price_usd
                    logger.info(f"Найден Transfer {amount_tokens} токенов от user.id={user.id} -> MY_WALLET, usd={amount_in_usd}.")

                    if amount_in_usd >= 25:  # например, 20$ "стейк" + 5$ сбор (в сумме)
                        # создаём запись UserStaking
                        staking = UserStaking(
                            user_id=user.id,
                            staked_amount_tokens=amount_tokens,
                            staked_amount_usd=amount_in_usd,
                            is_active=True
                        )
                        db.session.add(staking)
                        db.session.commit()

                        # Делаем assistant_premium = True (можно так)
                        user.assistant_premium = True
                        db.session.commit()
                        logger.info(f"user.id={user.id}: стейк принят, premium=ON.")
                    else:
                        logger.info(f"Сумма {amount_in_usd}$ < 25$, пропускаем.")
                else:
                    logger.info(f"from_addr={from_addr} не найден среди пользователей, пропускаем.")
            else:
                logger.debug(f"Transfer -> {to_addr}, не наш {MY_WALLET_ADDRESS}, пропуск...")

        # обновим last_block
        last_block_conf.value = str(current_block)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка scan_for_staking_transfers: {e}")
        logger.error(traceback.format_exc())
