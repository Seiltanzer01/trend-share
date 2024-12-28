# staking_logic.py

import os
import logging
import traceback
from datetime import datetime, timedelta
import requests

from web3 import Web3
from eth_account import Account

from models import db, User, UserStaking
# Из best_setup_voting импортируем уже инициализированные web3/token_contract, TOKEN_DECIMALS:
from best_setup_voting import web3, token_contract, TOKEN_DECIMALS

logger = logging.getLogger(__name__)

# Сюда пользователь отправляет токены
MY_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS", "")

DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/tokens"


def get_token_price_in_usd() -> float:
    """
    Получаем текущую цену нашего ERC20-токена (UJO) в USD,
    например, через DexScreener.
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
            logger.warning("DexScreener pairs отсутствуют или не вернулись.")
            return 0.0
        price_usd = float(pairs[0].get("priceUsd", 0.0))
        return price_usd
    except Exception as e:
        logger.error(f"Ошибка get_token_price_in_usd: {e}")
        return 0.0


def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """
    Фронтенд (Metamask) после успешной транзакции POST'ит txHash сюда.
    Мы проверяем:
      1) транзакция успешна (receipt.status == 1);
      2) Логи содержат Transfer(from=user.wallet_address, to=MY_WALLET_ADDRESS, >=25$);
      3) Создаём запись UserStaking(...).
    """
    if not user or not user.wallet_address or not tx_hash:
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

                        if (from_addr.lower() == user.wallet_address.lower() and
                            to_addr.lower()   == MY_WALLET_ADDRESS.lower()):
                            # Получаем amount из data
                            amount_int = int(log.data, 16)
                            amount_token = amount_int / (10 ** TOKEN_DECIMALS)
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
