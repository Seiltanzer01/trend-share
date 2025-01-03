# best_setup_voting.py

import os
import logging
import traceback
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, render_template, flash, redirect, url_for, session, current_app
from models import db, User, Trade, Setup, Criterion, Config, BestSetupCandidate, BestSetupVote, BestSetupPoll
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account

logger = logging.getLogger(__name__)

best_setup_voting_bp = Blueprint('best_setup_voting', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or 'telegram_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        from app import ADMIN_TELEGRAM_IDS
        if session['telegram_id'] not in ADMIN_TELEGRAM_IDS:
            flash('Доступ запрещён.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.assistant_premium:
            flash('Доступ запрещён. Приобретите премиум-подписку.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def ensure_wallet(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Сначала авторизуйтесь.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        if not user.wallet_address:
            flash('Для участия в голосовании введите свой адрес кошелька.', 'info')
            return redirect(url_for('best_setup_voting.set_wallet'))
        return f(*args, **kwargs)
    return decorated_function

def get_active_poll():
    now = datetime.utcnow()
    poll = BestSetupPoll.query.filter(BestSetupPoll.status == 'active', BestSetupPoll.end_date > now).first()
    return poll

### ЛОГИКА ОТПРАВКИ ТОКЕНОВ ###
BASE_RPC_URL = os.environ.get('BASE_RPC_URL', '')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY', '')
TOKEN_CONTRACT_ADDRESS = os.environ.get('TOKEN_CONTRACT_ADDRESS', '')
TOKEN_DECIMALS = int(os.environ.get('TOKEN_DECIMALS', '18'))

web3 = None
token_contract = None
account = None

if BASE_RPC_URL and PRIVATE_KEY and TOKEN_CONTRACT_ADDRESS:
    web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
    if web3.is_connected():
        logger.info("Подключено к RPC сети Base.")
        web3.middleware_onion.inject(geth_poa_middleware, layer=0)
        try:
            account = Account.from_key(PRIVATE_KEY)
            logger.info(f"Аккаунт инициализирован: {account.address}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации аккаунта: {e}")
            account = None

        ERC20_ABI = [
            {
                "constant": False,
                "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
                "name": "transfer",
                "outputs": [{"name": "success", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }
        ]

        try:
            token_contract = web3.eth.contract(
                address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
                abi=ERC20_ABI
            )
            logger.info(f"Токен-контракт инициализирован: {TOKEN_CONTRACT_ADDRESS}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации токен-контракта: {e}")
            token_contract = None
    else:
        logger.error("Не удалось подключиться к сети Base.")
else:
    logger.error("Не все необходимые переменные окружения установлены (BASE_RPC_URL, PRIVATE_KEY, TOKEN_CONTRACT_ADDRESS).")

def send_token_reward(user_wallet, amount):
    if not account or not token_contract:
        logger.error("Нет настроек для отправки токенов.")
        return False

    if not user_wallet or not user_wallet.startswith('0x') or len(user_wallet) != 42:
        logger.warning(f"Некорректный адрес кошелька: {user_wallet}")
        return False

    try:
        # Используем параметр 'pending' для корректного получения nonce
        nonce = web3.eth.get_transaction_count(account.address, 'pending')
        token_amount = int(amount * (10**TOKEN_DECIMALS))

        tx = token_contract.functions.transfer(
            Web3.to_checksum_address(user_wallet),
            token_amount
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': Web3.to_wei('1', 'gwei')
        })

        signed_tx = web3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt and receipt.status == 1:
            logger.info(f"Отправлено {amount} токенов на {user_wallet}. TX: {receipt.transactionHash.hex()}")
            return True
        else:
            logger.error(f"Транзакция неудачна или нет статуса: {receipt}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при отправке токенов: {e}")
        logger.error(traceback.format_exc())
        return False

### АНТИ-СПАМ МЕХАНИЗМ ###
def is_spammer(user_id):
    # Если хотя бы 2 дня из последних 7 дней было >=10 сделок в день, то спамщик.
    now = datetime.utcnow()
    spam_days = 0
    for i in range(7):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        daily_count = Trade.query.filter(
            Trade.user_id == user_id,
            Trade.trade_open_time >= day_start,
            Trade.trade_open_time < day_end
        ).count()
        if daily_count >= 10:
            spam_days += 1
    if spam_days >= 2:
        return True
    return False

def generate_s3_url(filename: str) -> str:
    bucket_name = current_app.config['AWS_S3_BUCKET']
    region = current_app.config['AWS_S3_REGION']
    if region == 'us-east-1':
        url = f"https://{bucket_name}.s3.amazonaws.com/{filename}"
    else:
        url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{filename}"
    return url

### ЛОГИКА ГОЛОСОВАНИЯ ###

@best_setup_voting_bp.route('/start_best_setup_contest', methods=['POST'])
@admin_required
def start_best_setup_contest():
    active_poll = get_active_poll()
    if active_poll:
        flash("Уже есть активное голосование.", "info")
        return redirect(url_for('admin_users'))

    last_poll_conf = Config.query.filter_by(key='last_best_setup_poll').first()
    if last_poll_conf:
        try:
            last_poll_date = datetime.strptime(last_poll_conf.value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # Попытка парсинга старого формата
            try:
                last_poll_date = datetime.strptime(last_poll_conf.value, '%Y-%m-%d')
                last_poll_conf.value = last_poll_date.strftime('%Y-%m-%d %H:%M:%S')
                db.session.commit()
                logger.info("last_best_setup_poll обновлён до нового формата.")
            except ValueError:
                flash("Неверный формат даты последнего голосования.", "danger")
                logger.error("Неверный формат даты в last_best_setup_poll.")
                return redirect(url_for('admin_users'))

        time_diff = datetime.utcnow() - last_poll_date
        if time_diff.total_seconds() / 60 < 15:
            flash("Голосование запускается раз в 15 минут, ещё рано.", "warning")
            return redirect(url_for('admin_users'))

    # Установка длительности голосования на 15 минут
    start_date = datetime.utcnow()
    end_date = start_date + timedelta(minutes=15)

    # Очистка предыдущих данных голосования
    try:
        BestSetupVote.query.delete()
        BestSetupCandidate.query.delete()
        BestSetupPoll.query.delete()
        db.session.commit()
        logger.info("Предыдущие данные голосования успешно удалены.")
    except Exception as e:
        logger.error(f"Ошибка при удалении предыдущих данных голосования: {e}")
        db.session.rollback()
        flash("Ошибка при инициализации нового голосования.", "danger")
        return redirect(url_for('admin_users'))

    # Создание нового голосования
    try:
        poll = BestSetupPoll(start_date=start_date, end_date=end_date, status='active')
        db.session.add(poll)
        db.session.commit()
        logger.info("Новое голосование успешно создано.")

        if not last_poll_conf:
            last_poll_conf = Config(key='last_best_setup_poll', value=start_date.strftime('%Y-%m-%d %H:%M:%S'))
            db.session.add(last_poll_conf)
        else:
            last_poll_conf.value = start_date.strftime('%Y-%m-%d %H:%M:%S')
        db.session.commit()
        logger.info("Конфигурация последнего голосования обновлена.")

        premium_users = User.query.filter_by(assistant_premium=True).all()
        candidates = []

        for user in premium_users:
            if is_spammer(user.id):
                logger.info(f"Пользователь {user.id} помечен как спамер и пропущен.")
                continue
            setups = user.setups
            for setup in setups:
                trades = Trade.query.filter_by(user_id=user.id, setup_id=setup.id).all()
                total_trades = len(trades)
                if total_trades < 2:
                    logger.info(f"Сетап {setup.id} пользователя {user.id} имеет недостаточное количество сделок.")
                    continue
                wins = sum(1 for t in trades if t.profit_loss and t.profit_loss > 0)
                win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0
                if win_rate < 70:
                    logger.info(f"Сетап {setup.id} пользователя {user.id} имеет низкий Win Rate {win_rate}%.")
                    continue
                candidates.append({
                    'user_id': user.id,
                    'setup_id': setup.id,
                    'total_trades': total_trades,
                    'win_rate': win_rate
                })

        candidates.sort(key=lambda x: (x['win_rate'], x['total_trades']), reverse=True)
        top_candidates = candidates[:15]
        logger.info(f"Найдено {len(top_candidates)} топ-кандидатов для голосования.")

        for c in top_candidates:
            candidate = BestSetupCandidate(
                user_id=c['user_id'],
                setup_id=c['setup_id'],
                total_trades=c['total_trades'],
                win_rate=c['win_rate']
            )
            db.session.add(candidate)
        db.session.commit()
        logger.info("Кандидаты успешно добавлены в новое голосование.")

        flash("Голосование запущено на 15 минут.", "success")
        return redirect(url_for('admin_users'))
    except Exception as e:
        logger.error(f"Ошибка при создании кандидатов или голосования: {e}")
        db.session.rollback()
        flash("Ошибка при инициализации нового голосования.", "danger")
        return redirect(url_for('admin_users'))

@best_setup_voting_bp.route('/best_setup_candidates', methods=['GET'])
@premium_required
def best_setup_candidates():
    poll = get_active_poll()
    if not poll:
        flash("Сейчас нет активного голосования.", "info")
        return redirect(url_for('index'))

    candidates = BestSetupCandidate.query.order_by(
        BestSetupCandidate.win_rate.desc(),
        BestSetupCandidate.total_trades.desc()
    ).all()
    candidates_list = []

    for c in candidates:
        setup = Setup.query.get(c.setup_id)
        if setup:
            screenshot_url = generate_s3_url(setup.screenshot) if setup.screenshot else None
            criteria_list = [criterion.name for criterion in setup.criteria]
        else:
            logger.warning(f"Setup with id {c.setup_id} not found for candidate {c.id}")
            screenshot_url = None
            criteria_list = []

        candidate_dict = {
            'id': c.id,
            'setup_name': setup.setup_name if setup else "Неизвестно",
            'description': setup.description if setup else "Нет описания",
            'screenshot_url': screenshot_url,
            'criteria': criteria_list,
            'total_trades': c.total_trades,
            'win_rate': c.win_rate
        }
        candidates_list.append(candidate_dict)

    logger.debug(f"Переданные кандидаты: {candidates_list}")

    return render_template('best_setup_candidates.html', candidates=candidates_list)

@best_setup_voting_bp.route('/vote_best_setup', methods=['POST'])
@premium_required
@ensure_wallet
def vote_best_setup():
    poll = get_active_poll()
    if not poll:
        flash("Нет активного голосования.", "info")
        return redirect(url_for('index'))

    logger.debug(f"Полученные данные формы: {request.form}")

    candidate_id = request.form.get('candidate_id')
    if not candidate_id:
        flash('Не выбран кандидат для голосования.', 'danger')
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    try:
        candidate_id = int(candidate_id)
    except ValueError:
        flash('Некорректный идентификатор кандидата.', 'danger')
        logger.error(f"Некорректный идентификатор кандидата: {candidate_id}")
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    candidate = BestSetupCandidate.query.get(candidate_id)
    if not candidate:
        flash('Неверный кандидат.', 'danger')
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    user_id = session['user_id']
    existing_vote = BestSetupVote.query.filter_by(
        voter_user_id=user_id,
        candidate_id=candidate_id
    ).first()
    if existing_vote:
        flash('Вы уже голосовали за этот сетап.', 'info')
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    vote = BestSetupVote(
        voter_user_id=user_id,
        candidate_id=candidate_id
    )
    db.session.add(vote)
    db.session.commit()

    flash('Ваш голос учтён!', 'success')
    return redirect(url_for('best_setup_voting.best_setup_candidates'))

@best_setup_voting_bp.route('/set_wallet', methods=['GET', 'POST'])
@premium_required
def set_wallet():
    user_id = session['user_id']
    user = User.query.get(user_id)
    if request.method == 'POST':
        wallet = request.form.get('wallet_address')
        if wallet and wallet.startswith('0x') and len(wallet) == 42:
            user.wallet_address = wallet
            db.session.commit()
            flash('Адрес кошелька успешно сохранён.', 'success')
            return redirect(url_for('best_setup_voting.best_setup_candidates'))
        else:
            flash('Некорректный адрес кошелька.', 'danger')

    return render_template('set_wallet.html', user=user)

def auto_finalize_best_setup_voting():
    poll = BestSetupPoll.query.filter_by(status='active').first()
    if not poll:
        return
    now = datetime.utcnow()
    if now >= poll.end_date:
        candidates = BestSetupCandidate.query.all()
        results = []
        for c in candidates:
            vote_count = BestSetupVote.query.filter_by(candidate_id=c.id).count()
            results.append((c, vote_count))

        results.sort(key=lambda x: x[1], reverse=True)
        winners = results[:3]

        # Пример наград
        rewards = [0.001, 0.0005, 0.0001]
        for i, (candidate, votes) in enumerate(winners):
            winner_user = User.query.get(candidate.user_id)
            if winner_user and winner_user.wallet_address:
                success = send_token_reward(winner_user.wallet_address, rewards[i])
                if success:
                    logger.info(f"Пользователь {winner_user.id} награждён {rewards[i]} токенами (место {i+1}).")
                else:
                    logger.error(f"Не удалось отправить токены пользователю {winner_user.id}.")

        voter_reward = 0.00005  # Награда для голосующих
        winner_candidate_ids = [w[0].id for w in winners]
        winning_votes = BestSetupVote.query.filter(
            BestSetupVote.candidate_id.in_(winner_candidate_ids)
        ).all()
        rewarded_voters = set()
        for vote in winning_votes:
            if vote.voter_user_id not in rewarded_voters:
                rewarded_voters.add(vote.voter_user_id)
                voter_user = User.query.get(vote.voter_user_id)
                if voter_user and voter_user.wallet_address:
                    success = send_token_reward(voter_user.wallet_address, voter_reward)
                    if success:
                        logger.info(f"Пользователь {voter_user.id} награждён {voter_reward} токенами за голос.")
                    else:
                        logger.error(f"Не удалось отправить токены пользователю {voter_user.id} (голосовавший).")

        poll.status = 'completed'
        db.session.commit()
        logger.info("Голосование завершено автоматически.")

@best_setup_voting_bp.route('/force_finalize_best_setup_voting', methods=['POST'])
@admin_required
def force_finalize_best_setup():
    """Принудительно завершаем текущее голосование для тестирования."""
    poll = BestSetupPoll.query.filter_by(status='active').first()
    if not poll:
        flash("Нет активного голосования для завершения.", "warning")
        return redirect(url_for('admin_users'))

    poll.end_date = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    auto_finalize_best_setup_voting()

    flash("Активное голосование принудительно завершено.", "success")
    return redirect(url_for('admin_users'))

def init_best_setup_voting_routes(app, db_instance):
    app.register_blueprint(best_setup_voting_bp)
