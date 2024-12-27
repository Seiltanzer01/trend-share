# staking_listener.py

import os
import logging
import traceback
import requests
from datetime import datetime
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account

from models import db, User, UserStaking
from flask import current_app
from decimal import Decimal

logger = logging.getLogger(__name__)

BASE_RPC_URL = os.environ.get('BASE_RPC_URL', '')
TOKEN_CONTRACT_ADDRESS = os.environ.get('TOKEN_CONTRACT_ADDRESS', '')
MY_WALLET_ADDRESS = os.environ.get('MY_WALLET_ADDRESS', '')  # Это ваш общий кошелёк
TOKEN_DECIMALS = int(os.environ.get('TOKEN_DECIMALS', '18'))

# Пример: для DexScreener API
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens"

# ABI для чтения Transfer-событий
ERC20_ABI = [
    {
        "anonymous":False,
        "inputs":[
            {"indexed":True,"name":"from","type":"address"},
            {"indexed":True,"name":"to","type":"address"},
            {"indexed":False,"name":"value","type":"uint256"}
        ],
        "name":"Transfer",
        "type":"event"
    },
    {
        "constant":True,
        "inputs":[{"name":"_owner","type":"address"}],
        "name":"balanceOf",
        "outputs":[{"name":"balance","type":"uint256"}],
        "type":"function"
    }
]

web3 = None
token_contract = None

def init_web3():
    global web3, token_contract
    if not BASE_RPC_URL or not TOKEN_CONTRACT_ADDRESS:
        logger.error("BASE_RPC_URL или TOKEN_CONTRACT_ADDRESS не установлены.")
        return
    
    web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
    if not web3.is_connected():
        logger.error("Не удалось подключиться к RPC.")
        return
    
    web3.middleware_onion.inject(geth_poa_middleware, layer=0)
    token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS), abi=ERC20_ABI)
    logger.info("staking_listener: web3 init success.")


def get_token_price_in_usd():
    """
    Пример запроса к DexScreener, чтобы получить цену токена в долларах.
    Нужно указать правильный dex или отдельную пару. 
    Если вы используете DexScreener, найдите slug. 
    Пример: 
      https://dexscreener.com/base/<address> 
    Ищите в JSON поле 'priceUsd'.
    """
    try:
        url = f"{DEXSCREENER_API}/{TOKEN_CONTRACT_ADDRESS}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        # Ожидаем data['pairs']...
        pairs = data.get('pairs', [])
        if not pairs:
            logger.warning("dexscreener: нет данных о парах.")
            return None
        
        # Берём первую пару, поля 'priceUsd'
        price_str = pairs[0].get('priceUsd')
        if not price_str:
            logger.warning("dexscreener: не найдена priceUsd в паре.")
            return None
        return Decimal(price_str)
    except Exception as e:
        logger.error(f"dexscreener error: {e}")
        return None


def scan_for_staking_transfers():
    """
    Сканируем последние события Transfer(...).
    Проверяем:
      - from == user.wallet_address
      - to == MY_WALLET_ADDRESS
      - amount >= 25$ (20$ стейк + 5$ fee)
    Потом создаём запись UserStaking(...) 
    и даём ассистент-премиум = True
    """
    if not web3 or not token_contract:
        init_web3()
        if not web3 or not token_contract:
            return
    
    try:
        # 1. Получаем текущий blockNumber
        latest_block = web3.eth.block_number
        
        # 2. Грузим логи за некий диапазон (например, ~ последние 2000 блоков)
        from_block = latest_block - 2000
        if from_block < 0:
            from_block = 0
        
        event_signature = web3.keccak(text="Transfer(address,address,uint256)").hex()
        # создадим фильтр
        logs = web3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": latest_block,
            "address": Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
            "topics": [event_signature]
        })
        if not logs:
            return
        
        price_usd = get_token_price_in_usd()
        if not price_usd:
            logger.info("Не удалось получить цену токена. Пропускаем проверку.")
            return

        for log_entry in logs:
            # Раскодируем (indexed data)
            # topic[1] = from, topic[2] = to
            from_address = "0x" + log_entry.topics[1].hex()[-40:]
            to_address = "0x" + log_entry.topics[2].hex()[-40:]
            
            # data = value (uint256)
            value_int = int(log_entry.data, 16)
            value_dec = Decimal(value_int) / Decimal(10**TOKEN_DECIMALS)
            
            # Проверяем "to" == MY_WALLET_ADDRESS
            if to_address.lower() != MY_WALLET_ADDRESS.lower():
                continue

            # Находим пользователя, у которого wallet_address == from_address
            user = User.query.filter_by(wallet_address=Web3.to_checksum_address(from_address)).first()
            if not user:
                continue  # не знаем, кто это

            # Считаем $-эквивалент
            usd_amount = value_dec * price_usd

            if usd_amount >= Decimal('25'):
                # 20$ + 5$ => создаём запись UserStaking
                # + даём assistant_premium = True
                # Проверим, нет ли уже записи?
                existing = UserStaking.query.filter_by(user_id=user.id).first()
                if existing:
                    if existing.stake_amount < value_dec:
                        existing.stake_amount = value_dec
                        existing.last_deposit_at = datetime.utcnow()
                else:
                    new_stake = UserStaking(
                        user_id=user.id,
                        stake_amount=value_dec,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(new_stake)
                
                user.assistant_premium = True
                db.session.commit()
                logger.info(f"Пользователь ID {user.id} внёс {usd_amount}$. Премиум активирован.")
                
    except Exception as e:
        logger.error(f"scan_for_staking_transfers error: {e}")
        logger.error(traceback.format_exc())
        db.session.rollback()
