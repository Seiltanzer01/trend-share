# staking_logic.py

import os
import logging
import traceback
from datetime import datetime
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account
import requests

from models import db, User, UserStaking  # <-- нужно создать модель UserStaking
from best_setup_voting import token_contract, TOKEN_DECIMALS, BASE_RPC_URL, PRIVATE_KEY
# token_contract уже проинициализирован в best_setup_voting (или можно отдельно).
# Либо, если хотите, можете отдельно подключиться.

logger = logging.getLogger(__name__)

MY_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "")  # ваш общий кошелек
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/tokens"  # пример

def get_token_price_in_usd() -> float:
    """
    Получение текущей цены (UJO->USD).
    Для примера: DEX Screener, или ваш API.
    Возвращает float (например, 1.23).
    """
    try:
        token_address = os.environ.get("TOKEN_CONTRACT_ADDRESS", "")
        if not token_address:
            logger.error("TOKEN_CONTRACT_ADDRESS not set.")
            return 0.0
        
        # Пример запроса DexScreener
        # https://api.dexscreener.com/latest/dex/tokens/0x...
        url = f"{DEXSCREENER_API_URL}/{token_address}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        # нужно адаптировать под реальный ответ DexScreener:
        # Пример ответа: data['pairs'][0]['priceUsd']
        
        pairs = data.get("pairs", [])
        if not pairs:
            logger.error("No pairs in DexScreener response")
            return 0.0
        
        price_usd = pairs[0].get("priceUsd", 0.0)
        price_usd = float(price_usd)
        return price_usd
    except Exception as e:
        logger.error(f"Error get_token_price_in_usd: {e}")
        return 0.0

def scan_for_staking_transfers(flask_app):
    """
    Сканируем последние Transfer-события, проверяем:
    - from == user.wallet_address
    - to == MY_WALLET_ADDRESS
    - amount >= 25$ (из них 20$ stake, 5$ fee)
    - если ok -> UserStaking(...) + assistant_premium=True
    """
    with flask_app.app_context():
        try:
            if not token_contract:
                logger.warning("token_contract not init, skip scanning.")
                return
            
            # Определяем, до какого блока уже просматривали
            conf_key = "last_checked_block"
            from models import Config
            block_conf = Config.query.filter_by(key=conf_key).first()
            if not block_conf:
                block_conf = Config(key=conf_key, value="0")
                db.session.add(block_conf)
                db.session.flush()
            
            last_checked_block = int(block_conf.value)
            
            web3 = token_contract.web3
            current_block = web3.eth.block_number
            
            # Событие Transfer(topics):
            # event Transfer(address indexed from, address indexed to, uint256 value)
            # keccak256("Transfer(address,address,uint256)")
            transfer_topic = web3.keccak(text="Transfer(address,address,uint256)").hex()
            
            # Запрос логов
            # ВНИМАНИЕ: если блокчейн большой, нужно разбивать на куски.
            logs = web3.eth.get_logs({
                "fromBlock": last_checked_block+1,
                "toBlock": current_block,
                "address": token_contract.address,
                "topics": [transfer_topic]
            })
            
            token_price_usd = get_token_price_in_usd()
            if token_price_usd <= 0:
                logger.warning("Invalid token_price_usd, skip.")
                return
            
            for entry in logs:
                tx_hash = entry.transactionHash.hex()
                data_hex = entry.data  # value
                # data_hex -> int
                value_int = int(data_hex, 16)
                
                topics = entry.topics
                # topics[1] = from
                # topics[2] = to
                # нужно убрать 12 байт префикса.
                
                from_addr = "0x" + topics[1].hex()[26:]
                to_addr   = "0x" + topics[2].hex()[26:]
                
                from_addr = Web3.to_checksum_address(from_addr)
                to_addr   = Web3.to_checksum_address(to_addr)
                
                # Переведём value из wei
                amount_token = value_int / (10**TOKEN_DECIMALS)
                # Посчитаем сумму в USD
                amount_usd = amount_token * token_price_usd
                
                # Проверяем условия:
                if to_addr.lower() == MY_WALLET_ADDRESS.lower():
                    # Найдём пользователя с таким wallet_address
                    user = User.query.filter_by(wallet_address=from_addr.lower()).first()
                    if user:
                        logger.info(f"Found Transfer from user {user.id} -> MY_WALLET. amount_usd={amount_usd:.2f}, tx={tx_hash}")
                        
                        # Проверяем минимум 25$
                        if amount_usd >= 25.0:
                            # делим логически: 20$ = stake, 5$ = fee
                            # Расчитаем пропорцию:
                            #   stake_tokens = 20 / price_usd
                            #   fee_tokens   = 5 / price_usd
                            # Но фактически всё 25$+ приходит вам.
                            
                            stake_usd = 20.0
                            fee_usd   = 5.0
                            stake_tokens = stake_usd / token_price_usd
                            fee_tokens   = fee_usd   / token_price_usd
                            
                            # Запись в БД
                            existing = UserStaking.query.filter_by(tx_hash=tx_hash).first()
                            if not existing:
                                new_stake = UserStaking(
                                    user_id = user.id,
                                    tx_hash = tx_hash,
                                    staked_usd = stake_usd,
                                    fee_usd = fee_usd,
                                    staked_amount = stake_tokens,
                                    fee_amount = fee_tokens,
                                    created_at = datetime.utcnow(),
                                    unlocked_at = datetime.utcnow() + timedelta(days=30)
                                )
                                db.session.add(new_stake)
                                
                                # Включаем премиум
                                user.assistant_premium = True
                                db.session.commit()
                                logger.info(f"User {user.id} staked successfully. staked={stake_tokens:.4f} fee={fee_tokens:.4f}")
            
            block_conf.value = str(current_block)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"scan_for_staking_transfers error: {e}")
            logger.error(traceback.format_exc())
