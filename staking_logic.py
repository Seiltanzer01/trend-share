# staking_logic.py

import os
import logging
import traceback
from datetime import datetime, timedelta
import requests

from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account

from models import db, User, UserStaking
# Импортируем отдельно и token_contract, и web3:
from best_setup_voting import token_contract, web3, TOKEN_DECIMALS, BASE_RPC_URL, PRIVATE_KEY

logger = logging.getLogger(__name__)

# Общий кошелёк, куда поступают стейки
MY_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "")
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/tokens"

def get_token_price_in_usd() -> float:
    """
    Получаем текущую цену токена UJO -> USD,
    используя DexScreener.
    """
    try:
        token_address = os.environ.get("TOKEN_CONTRACT_ADDRESS", "")
        if not token_address:
            logger.error("TOKEN_CONTRACT_ADDRESS не задан.")
            return 0.0

        url = f"{DEXSCREENER_API_URL}/{token_address}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        pairs = data.get("pairs", [])
        if not pairs:
            logger.warning("DexScreener pairs отсутствуют.")
            return 0.0
        price_usd = float(pairs[0].get("priceUsd", 0.0))
        return price_usd
    except Exception as e:
        logger.error(f"Ошибка get_token_price_in_usd: {e}")
        return 0.0

def scan_for_staking_transfers(flask_app):
    """
    Раз в 1 минуту сканируем Transfer-события (ERC20):
      - from=user.wallet_address
      - to=MY_WALLET_ADDRESS
      - Проверяем, что это >= 25$ (20 + 5 сбор)
      - Создаём запись UserStaking, user.assistant_premium = True
    """
    with flask_app.app_context():
        try:
            if not token_contract:
                logger.warning("token_contract = None, выходим.")
                return
            if not web3:
                logger.warning("web3 = None, выходим.")
                return

            from models import Config
            conf_key = "last_checked_block"
            block_conf = Config.query.filter_by(key=conf_key).first()
            if not block_conf:
                block_conf = Config(key=conf_key, value="0")
                db.session.add(block_conf)
                db.session.flush()

            last_checked_block = int(block_conf.value)
            current_block = web3.eth.block_number

            transfer_topic = web3.keccak(text="Transfer(address,address,uint256)").hex()

            logs = web3.eth.get_logs({
                "fromBlock": last_checked_block + 1,
                "toBlock": current_block,
                "address": token_contract.address,
                "topics": [transfer_topic]
            })

            price_usd = get_token_price_in_usd()
            if price_usd <= 0:
                logger.warning("Цена токена UJO = 0, пропускаем.")
                return

            for entry in logs:
                tx_hash = entry.transactionHash.hex()
                data_hex = entry.data  # количество в hex
                value_int = int(data_hex, 16)
                amount_token = value_int / (10**TOKEN_DECIMALS)
                amount_usd = amount_token * price_usd

                topics = entry.topics
                from_addr = "0x" + topics[1].hex()[26:]
                to_addr   = "0x" + topics[2].hex()[26:]

                from_addr = Web3.to_checksum_address(from_addr)
                to_addr   = Web3.to_checksum_address(to_addr)

                # Ищем нужные переводы
                if to_addr.lower() == MY_WALLET_ADDRESS.lower():
                    user = User.query.filter_by(wallet_address=from_addr.lower()).first()
                    if user:
                        logger.info(f"Transfer from user {user.id}, amount={amount_token:.4f} => {amount_usd:.2f}$, tx={tx_hash}")
                        # Нужно >= 25$
                        if amount_usd >= 25.0:
                            # проверим, не добавляли ли уже этот tx
                            existing = UserStaking.query.filter_by(tx_hash=tx_hash).first()
                            if not existing:
                                new_stake = UserStaking(
                                    user_id=user.id,
                                    tx_hash=tx_hash,
                                    staked_usd=amount_usd,
                                    staked_amount=amount_token,
                                    created_at=datetime.utcnow(),
                                    unlocked_at=datetime.utcnow() + timedelta(days=30),
                                    last_claim_at=datetime.utcnow()
                                )
                                db.session.add(new_stake)
                                user.assistant_premium = True
                                db.session.commit()
                                logger.info(f"User {user.id} staked ~{amount_usd:.2f}$ (tx={tx_hash}). Premium on.")

            block_conf.value = str(current_block)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            logger.error(f"scan_for_staking_transfers: {e}")
            logger.error(traceback.format_exc())

def accumulate_staking_rewards(flask_app):
    """
    Пример: раз в сутки (или раз в неделю) мы могли бы всем увеличить поле pending_rewards.
    """
    with flask_app.app_context():
        try:
            stakings = UserStaking.query.all()
            for s in stakings:
                if s.staked_amount > 0:
                    # имитируем: +0.5 UJO в pending_rewards
                    s.pending_rewards += 0.5
            db.session.commit()
            logger.info("accumulate_staking_rewards: награды добавлены.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"accumulate_staking_rewards: {e}")
            logger.error(traceback.format_exc())
