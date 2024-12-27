# staking.py

import os
import logging
import traceback
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account

logger = logging.getLogger(__name__)

BASE_RPC_URL = os.environ.get('BASE_RPC_URL', '')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY', '')
STAKING_CONTRACT_ADDRESS = os.environ.get('STAKING_CONTRACT_ADDRESS', '')  # Ваш задеплойленный адрес
TOKEN_DECIMALS = int(os.environ.get('TOKEN_DECIMALS', '18'))

# Вставьте ПОЛНЫЙ ABI (полученный при компиляции) ниже:
STAKING_CONTRACT_ABI = [
    {
        "inputs": [
            {
                "internalType": "contract IERC20",
                "name": "_stakingToken",
                "type": "address"
            }
        ],
        "stateMutability": "nonpayable",
        "type": "constructor"
    },
    ...
    // Полный ABI
]

web3 = None
staking_contract = None
owner_account = None

def init_staking_web3():
    global web3, staking_contract, owner_account
    if BASE_RPC_URL and PRIVATE_KEY and STAKING_CONTRACT_ADDRESS:
        web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
        if web3.is_connected():
            logger.info("Staking: connected to RPC.")
            web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            try:
                owner_account = Account.from_key(PRIVATE_KEY)
                logger.info(f"Staking: owner account = {owner_account.address}")
            except Exception as e:
                logger.error(f"Error init owner_account: {e}")
                return

            try:
                staking_contract = web3.eth.contract(
                    address=Web3.to_checksum_address(STAKING_CONTRACT_ADDRESS),
                    abi=STAKING_CONTRACT_ABI
                )
                logger.info(f"Staking contract init success: {STAKING_CONTRACT_ADDRESS}")
            except Exception as e:
                logger.error(f"Error init staking_contract: {e}")
        else:
            logger.error("Staking: not connected to RPC.")
    else:
        logger.error("Env not set: BASE_RPC_URL, PRIVATE_KEY, STAKING_CONTRACT_ADDRESS")

def stake_tokens_from_backend(amount_float: float):
    """
    Вызываем contract.stake(amount), подписывая транзакцию PRIVATE_KEY (owner).
    msg.sender будет owner_account. => Награды и unstake выплатятся owner_account.
    """
    if not web3 or not staking_contract or not owner_account:
        return False, "Staking contract not init"

    try:
        amount_int = int(amount_float * 10**TOKEN_DECIMALS)
        nonce = web3.eth.get_transaction_count(owner_account.address, 'pending')
        tx = staking_contract.functions.stake(amount_int).build_transaction({
            'from': owner_account.address,
            'nonce': nonce,
            'gas': 400000,
            'gasPrice': web3.to_wei('1', 'gwei')
        })
        signed = web3.eth.account.sign_transaction(tx, private_key=owner_account.key)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"Staking success: {receipt.transactionHash.hex()}")
            return True, f"Staked {amount_float} tokens"
        else:
            return False, "Stake tx failed"
    except Exception as e:
        logger.error(f"stake_tokens_from_backend error: {e}")
        logger.error(traceback.format_exc())
        return False, str(e)

def unstake_from_backend():
    """
    owner_account вызывает unstake() => контракт возвращает stake - fee + reward 
    на тот же address (owner_account).
    """
    if not web3 or not staking_contract or not owner_account:
        return False, "Staking contract not init"

    try:
        nonce = web3.eth.get_transaction_count(owner_account.address, 'pending')
        tx = staking_contract.functions.unstake().build_transaction({
            'from': owner_account.address,
            'nonce': nonce,
            'gas': 400000,
            'gasPrice': web3.to_wei('1', 'gwei')
        })
        signed = web3.eth.account.sign_transaction(tx, private_key=owner_account.key)
        tx_hash = web3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            logger.info(f"Unstake success: {receipt.transactionHash.hex()}")
            return True, f"Unstake OK"
        else:
            return False, "Unstake tx failed"
    except Exception as e:
        logger.error(f"unstake_from_backend error: {e}")
        logger.error(traceback.format_exc())
        return False, str(e)

def get_stake_of(address: str):
    """
    Вызов stakeOf(address).
    """
    if not web3 or not staking_contract:
        return 0.0
    try:
        staked = staking_contract.functions.stakeOf(Web3.to_checksum_address(address)).call()
        return staked / (10**TOKEN_DECIMALS)
    except Exception as e:
        logger.error(f"get_stake_of error: {e}")
        return 0.0
