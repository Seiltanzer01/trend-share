# staking_logic.py

import os
import logging
import traceback
from datetime import datetime, timedelta
import requests
import secrets
import string

from web3 import Web3
from eth_account import Account

from models import db, User, UserStaking

logger = logging.getLogger(__name__)

# Подключение к RPC (например, Base)
INFURA_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID")
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Адреса контрактов
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS", "0xYOUR_TOKEN_CONTRACT_ADDRESS")  # UJO
WETH_CONTRACT_ADDRESS  = os.environ.get("WETH_CONTRACT_ADDRESS",  "0xYOUR_WETH_CONTRACT_ADDRESS")  # WETH
UJO_CONTRACT_ADDRESS   = TOKEN_CONTRACT_ADDRESS  # Дубль, если UJO — тот же токен
PROJECT_WALLET_ADDRESS = os.environ.get("MY_WALLET_ADDRESS",      "0xYOUR_PROJECT_WALLET_ADDRESS")

# Проверка наличия необходимых переменных окружения
if (
    TOKEN_CONTRACT_ADDRESS == "0xYOUR_TOKEN_CONTRACT_ADDRESS"
    or WETH_CONTRACT_ADDRESS  == "0xYOUR_WETH_CONTRACT_ADDRESS"
    or PROJECT_WALLET_ADDRESS == "0xYOUR_PROJECT_WALLET_ADDRESS"
):
    logger.error("Одна или несколько ENV-переменных (TOKEN_CONTRACT_ADDRESS, WETH_CONTRACT_ADDRESS, MY_WALLET_ADDRESS) не заданы.")
    raise ValueError("Некорректные ENV для TOKEN_CONTRACT_ADDRESS/WETH_CONTRACT_ADDRESS/MY_WALLET_ADDRESS.")

# ERC20 ABI с decimals/transfer/balanceOf
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
            {"name": "_to",   "type": "address"},
            {"name": "_value","type": "uint256"}
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

# Для WETH также нужен метод deposit() (ABI)
WETH_ABI = ERC20_ABI + [
    {
        "constant": False,
        "inputs": [],
        "name": "deposit",
        "outputs": [],
        "payable": True,
        "type": "function"
    },
]

# Проверка корректности адресов
if not Web3.is_address(TOKEN_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный TOKEN_CONTRACT_ADDRESS: {TOKEN_CONTRACT_ADDRESS}")
if not Web3.is_address(WETH_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный WETH_CONTRACT_ADDRESS: {WETH_CONTRACT_ADDRESS}")
if not Web3.is_address(UJO_CONTRACT_ADDRESS):
    raise ValueError(f"Некорректный UJO_CONTRACT_ADDRESS: {UJO_CONTRACT_ADDRESS}")
if not Web3.is_address(PROJECT_WALLET_ADDRESS):
    raise ValueError(f"Некорректный PROJECT_WALLET_ADDRESS: {PROJECT_WALLET_ADDRESS}")

# Создаём объекты контрактов
token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS), abi=ERC20_ABI)
# Для WETH используем ABI с методом deposit()
weth_contract  = web3.eth.contract(address=Web3.to_checksum_address(WETH_CONTRACT_ADDRESS),  abi=WETH_ABI)
ujo_contract   = web3.eth.contract(address=Web3.to_checksum_address(UJO_CONTRACT_ADDRESS),   abi=ERC20_ABI)

# 0x Swap v2 (permit2)
ZEROX_API_KEY = os.environ.get("ZEROX_API_KEY", "")
DEFAULT_0X_HEADERS = {
    "0x-api-key": ZEROX_API_KEY,
    "0x-version": "v2",  # v2
}

def generate_unique_wallet_address():
    while True:
        address = '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(40))
        try:
            caddr = Web3.to_checksum_address(address)
        except ValueError:
            continue
        if not User.query.filter_by(unique_wallet_address=caddr).first():
            return caddr

def generate_unique_private_key():
    return '0x' + ''.join(secrets.choice(string.hexdigits.lower()) for _ in range(64))

def get_token_balance(wallet_address: str, contract=None) -> float:
    """Баланс указанного токена (по умолчанию UJO)."""
    try:
        if contract is None:
            contract = ujo_contract
        raw = contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        dec = contract.functions.decimals().call()
        return raw / (10 ** dec)
    except:
        logger.error("get_token_balance error", exc_info=True)
        return 0.0

def send_token_reward(to_address: str, amount: float, from_address: str = PROJECT_WALLET_ADDRESS, private_key: str = None) -> bool:
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

        # maxPriorityFeePerGas = 0.002 gwei, maxFeePerGas = 0.04 gwei
        priority_wei = Web3.to_wei(0.002, 'gwei')  # 0.002 gwei
        max_fee_wei  = Web3.to_wei(0.04, 'gwei')   # 0.04 gwei

        tx = token_contract.functions.transfer(
            Web3.to_checksum_address(to_address),
            amt_wei
        ).build_transaction({
            "chainId":  web3.eth.chain_id,
            "nonce":    web3.eth.get_transaction_count(acct.address, 'pending'),
            "gas":      50000,  # вместо 100000 или 50000
            "maxFeePerGas": max_fee_wei,
            "maxPriorityFeePerGas": priority_wei,
            "value": 0
        })
        signed_tx = acct.sign_transaction(tx)
        tx_hash   = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt   = web3.eth.wait_for_transaction_receipt(tx_hash, 180)

        if receipt.status == 1:
            logger.info(f"send_token_reward: {amount} UJO -> {to_address}, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"send_token_reward fail: {tx_hash.hex()}")
            return False
    except:
        logger.error("send_token_reward except", exc_info=True)
        return False
        
def send_eth(to_address: str, amount_eth: float, private_key: str) -> bool:
    try:
        acct = Account.from_key(private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        priority_wei = Web3.to_wei(0.002, 'gwei')  # 0.002 gwei
        max_fee_wei  = Web3.to_wei(0.04, 'gwei')   # 0.04 gwei

        tx = {
            "nonce": nonce,
            "to": Web3.to_checksum_address(to_address),
            "value": web3.to_wei(amount_eth, 'ether'),
            "chainId": web3.eth.chain_id,
            "maxFeePerGas": max_fee_wei,
            "maxPriorityFeePerGas": priority_wei,
            "gas": 50000  # хотя для простого transfer ETH обычно 21000, оставим 50000
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
    except:
        logger.error("send_eth error", exc_info=True)
        return False

def deposit_eth_to_weth(user_private_key: str, user_wallet: str, amount_eth: float) -> bool:
    try:
        acct = Account.from_key(user_private_key)
        nonce = web3.eth.get_transaction_count(acct.address, 'pending')

        priority_wei = Web3.to_wei(0.002, 'gwei')
        max_fee_wei  = Web3.to_wei(0.04, 'gwei')

        deposit_tx = weth_contract.functions.deposit().build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce":   nonce,
            "maxFeePerGas": max_fee_wei,
            "maxPriorityFeePerGas": priority_wei,
            "gas": 50000,  # deposit требует чуть больше 30k, возьмём запас
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
    except:
        logger.error("deposit_eth_to_weth except", exc_info=True)
        return False

def get_balances(user: User) -> dict:
    """ETH, WETH, UJO."""
    try:
        ua = Web3.to_checksum_address(user.unique_wallet_address)

        raw_eth = web3.eth.get_balance(ua)
        eth_bal = Web3.from_wei(raw_eth, 'ether')

        # WETH
        wdec  = weth_contract.functions.decimals().call()
        raw_w = weth_contract.functions.balanceOf(ua).call()
        wbal  = raw_w / (10 ** wdec)

        # UJO
        ujo_bal = get_token_balance(ua, ujo_contract)

        return {
            "balances": {
                "eth": float(eth_bal),
                "weth": float(wbal),
                "ujo": float(ujo_bal)
            }
        }
    except:
        logger.error("get_balances error", exc_info=True)
        return {"error": "Internal server error."}

def get_token_price_in_usd() -> float:
    """Допустим, DexScreener для сети base."""
    try:
        pair_address = os.environ.get("DEXScreener_PAIR_ADDRESS", "")
        if not pair_address:
            logger.error("DEXScreener_PAIR_ADDRESS не задан.")
            return 0.0
        chain_name = "base"
        api_url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_name}/{pair_address}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"DexScreener code={resp.status_code}")
            return 0.0
        data = resp.json()
        pair = data.get("pair", {})
        if not pair:
            return 0.0
        return float(pair.get("priceUsd", "0"))
    except:
        logger.error("get_token_price_in_usd except", exc_info=True)
        return 0.0

# --- 0x Swap v2 (permit2) ---
def get_0x_quote_v2_permit2(
    sell_token: str,
    buy_token: str,
    sell_amount_wei: int,
    taker_address: str,
    chain_id: int = 8453
) -> dict:
    """GET /swap/permit2/quote v2 (для сети Base по умолчанию)."""
    if not ZEROX_API_KEY:
        logger.error("ZEROX_API_KEY отсутствует.")
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
            logger.error(f"get_0x_quote_v2_permit2 error: {resp.text}")
            return {}
        return resp.json()
    except:
        logger.error("get_0x_quote_v2_permit2 except", exc_info=True)
        return {}

def execute_0x_swap_v2_permit2(quote_json: dict, private_key: str) -> bool:
    if not quote_json:
        logger.error("execute_0x_swap_v2_permit2: quote_json пуст.")
        return False

    tx_obj = quote_json.get("transaction", {})
    to_addr  = tx_obj.get("to")
    data_hex = tx_obj.get("data")
    val_str  = tx_obj.get("value", "0")
    gas_str  = tx_obj.get("gas", "200000")
    gp_str   = tx_obj.get("gasPrice", f"{web3.eth.gas_price}")

    if not to_addr or not data_hex:
        logger.error("execute_0x_swap_v2_permit2: нет to/data.")
        return False

    try:
        val_i = int(val_str)
        gas_i = int(gas_str)
        base_gas_price = int(gp_str)
    except:
        logger.error("execute_0x_swap_v2_permit2: parse value/gas/gasPrice fail.")
        return False

    # Задаём фиксированную низкую комиссию: 0.002 gwei priority + 0.04 gwei maxFee
    priority_wei = Web3.to_wei(0.002, 'gwei')
    max_fee_wei  = Web3.to_wei(0.04, 'gwei')

    acct = Account.from_key(private_key)
    nonce = web3.eth.get_transaction_count(acct.address, 'pending')

    tx = {
        "chainId": web3.eth.chain_id,
        "nonce":   nonce,
        "to":      Web3.to_checksum_address(to_addr),
        "data":    data_hex,
        "value":   val_i,
        "gas":     gas_i,  # 200000
        "maxFeePerGas":          max_fee_wei,
        "maxPriorityFeePerGas":  priority_wei,
    }

    try:
        signed_tx = acct.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"execute_0x_swap_v2_permit2 success, tx={tx_hash.hex()}")
            return True
        else:
            logger.error(f"execute_0x_swap_v2_permit2 fail, tx={tx_hash.hex()}")
            return False
    except:
        logger.error("execute_0x_swap_v2_permit2 except", exc_info=True)
        return False

def exchange_weth_to_ujo(wallet_address: str, amount_weth: float) -> bool:
    """Старый демо-обмен WETH->UJO (1:10)."""
    try:
        user = User.query.filter_by(unique_wallet_address=wallet_address).first()
        if not user or not user.unique_private_key:
            logger.error("exchange_weth_to_ujo: нет user/private_key.")
            return False

        wdec = weth_contract.functions.decimals().call()
        want = int(amount_weth * (10 ** wdec))
        have = weth_contract.functions.balanceOf(wallet_address).call()
        if have < want:
            logger.error("Недостаточно WETH.")
            return False

        acct      = Account.from_key(user.unique_private_key)
        base_fee  = web3.eth.gas_price
        priority  = Web3.to_wei(1, 'gwei')
        max_fee   = base_fee + priority
        nonce     = web3.eth.get_transaction_count(acct.address, 'pending')

        tx = weth_contract.functions.transfer(PROJECT_WALLET_ADDRESS, want).build_transaction({
            "chainId": web3.eth.chain_id,
            "nonce":   nonce,
            "gas": 50000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority,
        })
        signed = acct.sign_transaction(tx)
        thash  = web3.eth.send_raw_transaction(signed.rawTransaction)
        rcpt   = web3.eth.wait_for_transaction_receipt(thash, 180)
        if rcpt.status != 1:
            logger.error("Fail tx transferring WETH to project.")
            return False

        # Псевдо-курс 1 WETH = 10 UJO
        ujo_amt = amount_weth * 10
        ok      = send_token_reward(wallet_address, ujo_amt)
        return ok
    except:
        logger.error("exchange_weth_to_ujo except", exc_info=True)
        return False

def confirm_staking_tx(user: User, tx_hash: str) -> bool:
    """Если tx>=25$ => UserStaking+assistant_premium."""
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

        # Проверка дубля
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
    except:
        logger.error(f"confirm_staking_tx({tx_hash}) except", exc_info=True)
        db.session.rollback()
        return False

def accumulate_staking_rewards():
    """Раз в неделю можно вызвать."""
    try:
        st = UserStaking.query.all()
        for s in st:
            if s.staked_amount > 0:
                s.pending_rewards += 0.5
        db.session.commit()
    except:
        db.session.rollback()
        logger.error("accumulate_staking_rewards except", exc_info=True)
